"""OSM exposure per zone (plain deterministic code; stdlib PBF reader).

Contract:
- Reads the country profile's ``osm_extract`` (a repo-relative
  ``data/osm/<name>-<YYMMDD>.osm.pbf`` path, or a bare slug resolved by
  glob under ``data/osm/``). A missing/ambiguous extract fails BEFORE any
  UPDATE, leaving ``zones.exposure`` untouched (NULL stays NULL).
- Exposure is a RAW density, mirroring ``crater_evidence``
  (scripts/seed_db.py): exposure features assigned to the zone divided by
  the zone's geodesic area in km2 (pyproj Geod; no stored area column).
  It is finite and >= 0 by construction; pipelines/scoring.py owns the
  per-country log normalization. Never pre-normalize or pre-log here.
- A zone inside a parsed country extract with zero features gets a real
  0.0 (the extract covers the whole country), NOT NULL. NULL means only
  "no extract was parsed for this country" (e.g. vietnam today).
- Writes ONLY ``zones.exposure`` for that country's zones, in one
  transaction. priority_score/priority_rank/scored_at belong to
  pipelines/scoring.py; run it separately afterwards.
- Idempotent: every run is a full deterministic recompute/overwrite.

Exposure feature definition (v1, equal weight 1 per OSM element):
an element (node or way; relations are counted and skipped in v1) whose
tags match ANY of: ``building`` (settlement proxy; place=* nodes are too
sparse in these extracts to stand alone), settlement ``place`` values,
``amenity=school``/``building=school``, any ``highway`` (roads), or
farmland/residential ``landuse`` values. An element matching several
categories counts ONCE toward exposure; per-category counts are printed
as provenance. Ways are assigned by the mean of their node coordinates
(a representative point), then a seed_db-style STRtree point-in-zone join;
multi-hit boundary points go to the smallest zone id. Known v1 limits:
road length / landuse area are not weighted, and a school node inside a
school building way counts as two elements.

The PBF reader is hand-rolled on struct+zlib+protobuf-wire because no
PBF library (pyosmium/osmium/ogr2ogr) is installed; it adds no new
dependency (shapely/pyproj are already used by scripts/seed_db.py).
Field numbers follow osmformat.proto as observed in the pinned
Geofabrik files (DenseNodes: ids=1, lat=8, lon=9, keys_vals=10;
Way: id=1, keys=2, vals=3, refs=8).
"""

import json
import math
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `python pipelines/osm_exposure.py`

PLACE_VALUES = {"village", "town", "city", "hamlet", "suburb", "neighbourhood",
                "quarter", "isolated_dwelling", "farm"}
LANDUSE_VALUES = {"farmland", "farmyard", "orchard", "meadow", "residential"}
CATEGORIES = ("building", "place", "school", "highway", "landuse")


def feature_categories(tags: dict) -> set:
    """Exposure categories matched by one element's tags (empty = skip)."""
    cats = set()
    building = tags.get("building")
    if building and building != "no":
        cats.add("building")
    if tags.get("place") in PLACE_VALUES:
        cats.add("place")
    if tags.get("amenity") == "school" or building == "school":
        cats.add("school")
    if tags.get("highway"):
        cats.add("highway")
    if tags.get("landuse") in LANDUSE_VALUES:
        cats.add("landuse")
    return cats


# --- minimal protobuf-wire / OSM PBF reader (stdlib only) -----------------

def _varint(buf, pos):
    shift = result = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def _zigzag(n):
    return (n >> 1) ^ -(n & 1)


def _signed64(n):
    return n - (1 << 64) if n >= (1 << 63) else n


def _fields(buf):
    """[(field_number, value)] with varints as int, length-delimited as bytes."""
    pos, out = 0, []
    end = len(buf)
    while pos < end:
        tag, pos = _varint(buf, pos)
        num, wire = tag >> 3, tag & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 2:
            size, pos = _varint(buf, pos)
            value, pos = buf[pos:pos + size], pos + size
        elif wire == 5:
            value, pos = buf[pos:pos + 4], pos + 4
        elif wire == 1:
            value, pos = buf[pos:pos + 8], pos + 8
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        out.append((num, value))
    return out


def _packed(buf):
    pos, out = 0, []
    end = len(buf)
    while pos < end:
        value, pos = _varint(buf, pos)
        out.append(value)
    return out


def _cumsum_zigzag(values):
    out, total = [], 0
    for v in values:
        total += _zigzag(v)
        out.append(total)
    return out


def _iter_blocks(path):
    """Yield (blob_type, raw_bytes) for every blob; validates exact EOF."""
    data = Path(path).read_bytes()
    pos, end = 0, len(data)
    while pos < end:
        if pos + 4 > end:
            raise ValueError(f"{path}: truncated blob header at {pos}")
        (hlen,) = struct.unpack(">I", data[pos:pos + 4])
        pos += 4
        header = dict(_fields(data[pos:pos + hlen]))
        pos += hlen
        datasize = header[3]
        blob = dict(_fields(data[pos:pos + datasize]))
        pos += datasize
        raw = blob.get(1)
        if raw is None:
            raw = zlib.decompress(blob[3])
        if 2 in blob and len(raw) != blob[2]:
            raise ValueError(f"{path}: blob raw_size {blob[2]} != {len(raw)}")
        yield header[1].decode("utf-8"), raw
    if pos != end:
        raise ValueError(f"{path}: {end - pos} trailing bytes")


def _parse_primitive_block(raw):
    strings, groups = [], []
    granularity, lat_offset, lon_offset = 100, 0, 0
    for num, value in _fields(raw):
        if num == 1:
            strings = [v.decode("utf-8", "replace")
                       for sn, v in _fields(value) if sn == 1]
        elif num == 2:
            groups.append(value)
        elif num == 17:
            granularity = value
        elif num == 19:
            lat_offset = _signed64(value)
        elif num == 20:
            lon_offset = _signed64(value)
    return strings, groups, granularity, lat_offset, lon_offset


def _coord(raw_value, offset, granularity):
    return 1e-9 * (offset + granularity * raw_value)


def _tags(strings, keys, vals):
    return {strings[k]: strings[v] for k, v in zip(keys, vals)}


def _dense_nodes(messages):
    """Decode one DenseNodes message: ([ids], [lat_raw], [lon_raw], [tags|None])."""
    ids = _cumsum_zigzag(_packed(messages[1]))
    lats = _cumsum_zigzag(_packed(messages[8]))
    lons = _cumsum_zigzag(_packed(messages[9]))
    tags_list = [None] * len(ids)
    if 10 in messages:
        kv = _packed(messages[10])
        pos = 0
        for i in range(len(ids)):
            if pos < len(kv) and kv[pos] != 0:
                tags = {}
                while pos < len(kv) and kv[pos] != 0:
                    tags[kv[pos]] = kv[pos + 1]
                    pos += 2
                tags_list[i] = tags  # string-table indices, resolved by caller
            pos += 1  # the 0 separator (present for tagged and untagged alike)
    return ids, lats, lons, tags_list


def _scan_elements(path, want_coords=None):
    """One pass over the PBF.

    want_coords=None (pass 1): returns exposure node points, exposure way
    node-refs, and element counters. want_coords=<set of node ids>
    (pass 2): returns coordinates for just those ids.
    """
    stats = {"nodes": 0, "ways": 0, "relations": 0, "exposure_nodes": 0,
             "exposure_ways": 0, "invalid_points": 0}
    by_category = {c: 0 for c in CATEGORIES}
    points = []       # (lon, lat, categories) for exposure nodes
    way_refs = []     # ([node ids], categories) for exposure ways
    coords = {}       # pass 2 only: node id -> (lon, lat)

    def keep_point(lon, lat, cats):
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            stats["invalid_points"] += 1
            return
        points.append((lon, lat, cats))
        for c in cats:
            by_category[c] += 1

    for blob_type, raw in _iter_blocks(path):
        if blob_type != "OSMData":
            continue
        strings, groups, gran, lat_off, lon_off = _parse_primitive_block(raw)
        for group in groups:
            for num, value in _fields(group):
                if num == 2:  # DenseNodes
                    ids, lats, lons, tags_list = _dense_nodes(dict(_fields(value)))
                    stats["nodes"] += len(ids)
                    for nid, la, lo, idx_tags in zip(ids, lats, lons, tags_list):
                        lon = _coord(lo, lon_off, gran)
                        lat = _coord(la, lat_off, gran)
                        if want_coords is not None:
                            if nid in want_coords:
                                coords[nid] = (lon, lat)
                        elif idx_tags:
                            cats = feature_categories(
                                {strings[k]: strings[v] for k, v in idx_tags.items()})
                            if cats:
                                stats["exposure_nodes"] += 1
                                keep_point(lon, lat, cats)
                elif num == 1:  # plain Node (rare; these extracts are dense)
                    stats["nodes"] += 1
                    msg = dict(_fields(value))
                    if want_coords is not None:
                        nid = _zigzag(msg[1])
                        if nid in want_coords:
                            la, lo = (msg[8], msg[9]) if 8 in msg else (msg[6], msg[7])
                            coords[nid] = (_coord(_zigzag(lo), lon_off, gran),
                                           _coord(_zigzag(la), lat_off, gran))
                    elif 2 in msg:
                        cats = feature_categories(
                            _tags(strings, _packed(msg[2]), _packed(msg[3])))
                        if cats:
                            la, lo = (msg[8], msg[9]) if 8 in msg else (msg[6], msg[7])
                            stats["exposure_nodes"] += 1
                            keep_point(_coord(_zigzag(lo), lon_off, gran),
                                       _coord(_zigzag(la), lat_off, gran), cats)
                elif num == 3 and want_coords is None:  # Way
                    stats["ways"] += 1
                    msg = dict(_fields(value))
                    if 2 in msg:
                        cats = feature_categories(
                            _tags(strings, _packed(msg[2]), _packed(msg[3])))
                        if cats:
                            stats["exposure_ways"] += 1
                            way_refs.append((_cumsum_zigzag(_packed(msg[8])), cats))
                elif num == 4:  # Relation: counted, skipped in v1
                    stats["relations"] += 1
    return {"points": points, "way_refs": way_refs, "coords": coords,
            "stats": stats, "by_category": by_category}


def parse_pbf_features(path):
    """Parse a PBF into exposure representative points + provenance counters.

    Returns (points, info) where points = [(lon, lat, categories), ...]
    (one per exposure node/way) and info holds element/feature counters.
    Raises FileNotFoundError/ValueError on a missing or corrupt file.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"OSM extract not found: {path}")
    first = _scan_elements(path)
    points = list(first["points"])
    by_category = dict(first["by_category"])
    invalid_ways = 0
    if first["way_refs"]:
        want = set()
        for refs, _cats in first["way_refs"]:
            want.update(refs)
        coords = _scan_elements(path, want_coords=want)["coords"]
        for refs, cats in first["way_refs"]:
            pts = [coords[r] for r in refs if r in coords]
            if not pts:
                invalid_ways += 1
                continue
            lon = sum(p[0] for p in pts) / len(pts)
            lat = sum(p[1] for p in pts) / len(pts)
            if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                invalid_ways += 1
                continue
            points.append((lon, lat, cats))
            for c in cats:
                by_category[c] += 1
    info = dict(first["stats"])
    info["invalid_ways"] = invalid_ways
    info["features"] = len(points)
    info["by_category"] = by_category
    return points, info


# --- zone aggregation (seed_db STRtree / Geod pattern) --------------------

def aggregate_zones(zones, points):
    """Assign each point to its covering zone; return density per zone id.

    zones = [{"id", "geom" (shapely), "area_km2"}, ...];
    points = [(lon, lat, categories), ...]. Returns (exposure, counters)
    with exposure[id] = count/area_km2 (0.0 when count is 0). Points are
    never guessed into a zone: no cover = outside.
    """
    import shapely
    from shapely import STRtree

    counts = {z["id"]: 0 for z in zones}
    assigned = outside = multi_hit = 0
    if zones and points:
        tree = STRtree([z["geom"] for z in zones])
        pts = shapely.points([p[0] for p in points], [p[1] for p in points])
        # Points only: "intersects" is point-in-polygon incl. the boundary
        # (the STRtree predicate reads input-vs-tree, so zone-covers-point
        # is written this way; "within" would drop boundary points).
        point_idx, zone_idx = tree.query(pts, predicate="intersects")
        hits = {}
        for pi, zi in zip(point_idx.tolist(), zone_idx.tolist()):
            hits.setdefault(pi, []).append(zi)
        for pi in range(len(points)):
            found = hits.get(pi)
            if not found:
                outside += 1
                continue
            if len(found) > 1:
                multi_hit += 1
                found.sort(key=lambda zi: zones[zi]["id"])
            counts[zones[found[0]]["id"]] += 1
            assigned += 1
    elif points:
        outside = len(points)
    exposure = {}
    for z in zones:
        area = z["area_km2"]
        if not area or not math.isfinite(area) or area <= 0:
            raise ValueError(f"zone {z['id']}: invalid area_km2 {area!r}")
        exposure[z["id"]] = counts[z["id"]] / area
    counters = {"assigned": assigned, "outside": outside, "multi_hit": multi_hit,
                "counts": counts}
    return exposure, counters


def resolve_extract(osm_extract, repo_root=None):
    """Resolve a profile osm_extract to one PBF path (fail on 0 or many)."""
    from backend.app.config import REPO_ROOT

    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    value = str(osm_extract)
    if value.endswith(".osm.pbf") or "/" in value or "\\" in value:
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            raise FileNotFoundError(f"OSM extract not found: {path}")
        return path
    matches = sorted((root / "data" / "osm").glob(f"{value}-*.osm.pbf"))
    exact = root / "data" / "osm" / f"{value}.osm.pbf"
    if exact.exists():
        matches.append(exact)
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected exactly one data/osm/{value}*.osm.pbf, found "
            f"{len(matches)}: {[m.name for m in matches]}")
    return matches[0]


def exposure_country(country_id: str, db_path=None, pbf_path=None,
                     osm_extract=None) -> dict:
    """Compute + write zones.exposure for one country. Mirrors score_country."""
    import shapely
    from pyproj import Geod
    from shapely.geometry import shape

    from backend.app.db import get_conn

    if pbf_path is None:
        if osm_extract is None:
            from backend.app.profiles import load_country
            osm_extract = load_country(country_id)["osm_extract"]
        pbf_path = resolve_extract(osm_extract)
    # Parse fully BEFORE opening/writing the DB: a bad extract changes nothing.
    points, info = parse_pbf_features(pbf_path)

    conn = get_conn(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, geom FROM zones WHERE country = ? ORDER BY id",
            (country_id,))]
        geod = Geod(ellps="WGS84")
        zones = []
        for row in rows:
            geom = shapely.make_valid(shape(json.loads(row["geom"])))
            zones.append({"id": row["id"], "geom": geom,
                          "area_km2": abs(geod.geometry_area_perimeter(geom)[0]) / 1e6})
        exposure, counters = aggregate_zones(zones, points)
        for zid, value in exposure.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"zone {zid}: exposure must be finite >= 0, got {value!r}")
        with conn:
            conn.executemany(
                "UPDATE zones SET exposure = ? WHERE id = ?",
                [(exposure[z["id"]], z["id"]) for z in zones])
    finally:
        conn.close()
    values = list(exposure.values())
    return {
        "country": country_id,
        "pbf": str(pbf_path),
        "zones": len(zones),
        "zones_with_exposure": sum(1 for v in values if v > 0),
        "zones_zero": sum(1 for v in values if v == 0),
        "exposure_min": min(values) if values else None,
        "exposure_max": max(values) if values else None,
        "features": info["features"],
        "assigned": counters["assigned"],
        "outside": counters["outside"],
        "multi_hit": counters["multi_hit"],
        "invalid_ways": info["invalid_ways"],
        "invalid_points": info["invalid_points"],
        "elements": {"nodes": info["nodes"], "ways": info["ways"],
                     "relations": info["relations"]},
        "by_category": info["by_category"],
    }


if __name__ == "__main__":
    from pipelines._profile import country_arg

    profile = country_arg()
    try:
        summary = exposure_country(profile["id"], osm_extract=profile["osm_extract"])
    except FileNotFoundError as exc:
        print(f"[osm_exposure] {exc}", file=sys.stderr)
        print("[osm_exposure] no zones updated; exposure left as-is (NULL).",
              file=sys.stderr)
        sys.exit(1)
    print(f"[osm_exposure] {summary['country']}: {summary['zones']} zones, "
          f"{summary['zones_with_exposure']} with exposure>0, "
          f"{summary['zones_zero']} at 0.0 "
          f"(min {summary['exposure_min']:.6g}, max {summary['exposure_max']:.6g} features/km2)")
    print(f"[osm_exposure] features {summary['features']} = assigned {summary['assigned']} "
          f"+ outside {summary['outside']}; multi-hit {summary['multi_hit']}; "
          f"invalid ways/points {summary['invalid_ways']}/{summary['invalid_points']}; "
          f"elements {summary['elements']}; by category {summary['by_category']}")
    print(f"[osm_exposure] source {summary['pbf']}")
    print("[osm_exposure] priority scores untouched; run pipelines/scoring.py next.")
