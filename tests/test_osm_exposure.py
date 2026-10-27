"""OSM exposure tests: synthetic tiny PBF only (never the 95MB extracts).

The fixture PBF is generated in tmp_path by a minimal writer for the same
osmformat wire shape the pinned Geofabrik files use (DenseNodes,
delta/zigzag coding, zlib blobs), so parsing, filtering, aggregation,
0-vs-NULL semantics, and idempotency are all exercised without real data.
"""

import json
import sqlite3
import struct
import zlib
from pathlib import Path

import pytest
import shapely
from shapely.geometry import box, mapping

from pipelines.osm_exposure import (aggregate_zones, exposure_country,
                                    feature_categories, parse_pbf_features,
                                    resolve_extract)
from pipelines.scoring import score_country

SCHEMA = Path(__file__).resolve().parents[1] / "db" / "schema.local.sql"
REAL_PBF = Path(__file__).resolve().parents[1] / "data" / "osm" / "laos-261025.osm.pbf"


# --- minimal PBF writer (test fixture generation only) ---------------------

def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _zig(n):
    return n * 2 if n >= 0 else -n * 2 - 1


def _var_field(num, value):
    return _varint((num << 3) | 0) + _varint(value)


def _bytes_field(num, payload):
    return _varint((num << 3) | 2) + _varint(len(payload)) + payload


def _packed_field(num, values):
    return _bytes_field(num, b"".join(_varint(v) for v in values))


def _packed_zig_delta(num, values):
    out, prev = [], 0
    for v in values:
        out.append(_zig(v - prev))
        prev = v
    return _packed_field(num, out)


def _blob(blob_type, raw):
    blob = _var_field(2, len(raw)) + _bytes_field(3, zlib.compress(raw))
    header = _bytes_field(1, blob_type.encode()) + _var_field(3, len(blob))
    return struct.pack(">I", len(header)) + header + blob


def _raw_coord(degrees):
    return round(degrees * 10_000_000)  # granularity 100 -> 1e-7 deg units


def write_tiny_pbf(path):
    """Nodes/ways around zone A (lon 100-101, lat 15-16) and outside it."""
    nodes = [  # (id, lon, lat, tags)
        (1, 100.5, 15.5, {"place": "village"}),
        (2, 100.6, 15.5, {"amenity": "school"}),
        (3, 100.5, 15.6, {"amenity": "cafe"}),          # not exposure
        (4, 105.0, 20.0, {"building": "yes"}),           # outside every zone
        (5, 100.2, 15.2, {}), (6, 100.3, 15.2, {}),      # building way corners
        (7, 100.3, 15.3, {}), (8, 100.2, 15.3, {}),
        (9, 100.4, 15.4, {}), (10, 100.8, 15.4, {}),     # highway way refs
        (11, 100.7, 15.7, {}), (12, 100.9, 15.7, {}),    # farmland way refs
        (13, 100.9, 15.9, {}), (14, 100.7, 15.9, {}),
        (15, 101.0, 15.5, {"place": "hamlet"}),          # on zone A boundary
    ]
    ways = [  # (id, refs, tags)
        (10, [5, 6, 7, 8, 5], {"building": "yes"}),
        (11, [9, 10], {"highway": "residential"}),
        (12, [11, 12, 13, 14, 11], {"landuse": "farmland"}),
        (13, [999], {"building": "yes"}),                # unresolvable -> invalid
        (14, [9, 10], {"natural": "water"}),             # not exposure
        (15, [9, 999], {"highway": "residential"}),      # partial: placed from node 9
    ]
    strings = [""]

    def sidx(s):
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    kv = []
    for *_xy, tags in [(n[1], n[2], n[3]) for n in nodes]:
        for k, v in tags.items():
            kv += [sidx(k), sidx(v)]
        kv.append(0)
    way_msgs = []
    for wid, refs, tags in ways:
        way_msgs.append(
            _var_field(1, wid)
            + _packed_field(2, [sidx(k) for k in tags])
            + _packed_field(3, [sidx(v) for v in tags.values()])
            + _packed_zig_delta(8, refs))
    # String table must be built after every sidx() call above.
    string_table = b"".join(_bytes_field(1, s.encode()) for s in strings)
    dense = (_packed_zig_delta(1, [n[0] for n in nodes])
             + _packed_zig_delta(8, [_raw_coord(n[2]) for n in nodes])
             + _packed_zig_delta(9, [_raw_coord(n[1]) for n in nodes])
             + _packed_field(10, kv))
    group = _bytes_field(2, dense) + b"".join(_bytes_field(3, w) for w in way_msgs)
    block = _bytes_field(1, string_table) + _bytes_field(2, group)
    Path(path).write_bytes(_blob("OSMHeader", b"") + _blob("OSMData", block))
    return path


def square_zone(zid, lon0, lat0, lon1, lat1, area_km2=100.0):
    return {"id": zid, "geom": shapely.MultiPolygon([box(lon0, lat0, lon1, lat1)]),
            "area_km2": area_km2}


# --- feature filtering ------------------------------------------------------

def test_feature_categories():
    assert feature_categories({"building": "yes"}) == {"building"}
    assert feature_categories({"building": "school"}) == {"building", "school"}
    assert feature_categories({"building": "no"}) == set()
    assert feature_categories({"place": "village"}) == {"place"}
    assert feature_categories({"place": "island"}) == set()
    assert feature_categories({"amenity": "school"}) == {"school"}
    assert feature_categories({"amenity": "cafe"}) == set()
    assert feature_categories({"highway": "track"}) == {"highway"}
    assert feature_categories({"landuse": "farmland"}) == {"landuse"}
    assert feature_categories({"landuse": "forest"}) == set()
    assert feature_categories({}) == set()


# --- PBF parsing ------------------------------------------------------------

def test_parse_tiny_pbf(tmp_path):
    points, info = parse_pbf_features(write_tiny_pbf(tmp_path / "tiny.osm.pbf"))
    assert info["nodes"] == 15 and info["ways"] == 6 and info["relations"] == 0
    assert info["exposure_nodes"] == 4 and info["exposure_ways"] == 5
    assert info["invalid_ways"] == 1  # way 13 refs only a missing node
    assert info["partial_ways"] == 1  # way 15 placed from node 9, ref 999 missing
    assert info["features"] == 8 and len(points) == 8
    assert info["by_category"] == {"building": 2, "place": 2, "school": 1,
                                   "highway": 2, "landuse": 1}
    village = next(p for p in points if p[2] == {"place"} and p[0] == pytest.approx(100.5))
    assert village[1] == pytest.approx(15.5)
    # Building way representative point = mean of its 4 distinct corners
    # (closed way [5,6,7,8,5]: closing repeat excluded; (100.2+100.3+100.3+100.2)/4).
    building_pts = sorted(p[0] for p in points if "building" in p[2])
    assert building_pts[0] == pytest.approx(100.25)
    assert building_pts[1] == pytest.approx(105.0)
    # Partial way point is its sole surviving ref (node 9).
    partial = next(p for p in points if p[2] == {"highway"}
                   and p[0] == pytest.approx(100.4))
    assert partial[1] == pytest.approx(15.4)


def test_parse_two_byte_file_raises_value_error(tmp_path):
    tiny = tmp_path / "tiny2.osm.pbf"
    tiny.write_bytes(b"\x00\x00")
    with pytest.raises(ValueError):
        parse_pbf_features(tiny)


def test_parse_unsupported_blob_compression_raises_value_error(tmp_path):
    blob = _var_field(2, 4) + _bytes_field(4, b"lzma")  # field 4: neither raw nor zlib
    header = _bytes_field(1, b"OSMData") + _var_field(3, len(blob))
    path = tmp_path / "lzma.osm.pbf"
    path.write_bytes(struct.pack(">I", len(header)) + header + blob)
    with pytest.raises(ValueError, match="unsupported blob compression"):
        parse_pbf_features(path)


def test_parse_missing_and_corrupt(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_pbf_features(tmp_path / "nope.osm.pbf")
    bad = tmp_path / "bad.osm.pbf"
    bad.write_bytes(b"not a pbf")
    with pytest.raises(Exception):
        parse_pbf_features(bad)


@pytest.mark.skipif(not REAL_PBF.exists(), reason="real extract not present")
def test_real_extract_first_blob_is_header():
    # Cheap header check only; full parsing is the pipeline run, not the suite.
    from pipelines.osm_exposure import _iter_blocks
    blob_type, _raw = next(_iter_blocks(REAL_PBF))
    assert blob_type == "OSMHeader"


# --- point-in-zone aggregation ----------------------------------------------

def test_aggregate_counts_density_outside_and_boundary():
    zones = [square_zone("A", 100, 15, 101, 16, area_km2=50.0),
             square_zone("B", 102, 15, 103, 16, area_km2=25.0)]
    points = [(100.5, 15.5, {"place"}), (100.6, 15.5, {"school"}),
              (101.0, 15.5, {"place"}),   # boundary: covers includes it
              (105.0, 20.0, {"building"})]  # outside: never guessed
    exposure, counters = aggregate_zones(zones, points)
    assert exposure == {"A": 3 / 50.0, "B": 0.0}
    assert counters["assigned"] == 3 and counters["outside"] == 1
    assert counters["counts"] == {"A": 3, "B": 0}


def test_aggregate_multi_hit_picks_smallest_zone_id():
    zones = [square_zone("B", 100, 15, 101, 16), square_zone("A", 100, 15, 101, 16)]
    exposure, counters = aggregate_zones(zones, [(100.5, 15.5, {"place"})])
    assert counters["multi_hit"] == 1
    assert counters["counts"] == {"A": 1, "B": 0}
    assert exposure["A"] == pytest.approx(0.01)


def test_resolve_extract_slug_path_and_ambiguous(tmp_path):
    osm = tmp_path / "data" / "osm"
    osm.mkdir(parents=True)
    only = osm / "laos-261025.osm.pbf"
    only.write_bytes(b"x")
    assert resolve_extract("laos", repo_root=tmp_path) == only
    assert resolve_extract("data/osm/laos-261025.osm.pbf", repo_root=tmp_path) == tmp_path / only.relative_to(tmp_path)
    (osm / "laos-261026.osm.pbf").write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        resolve_extract("laos", repo_root=tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_extract("vietnam", repo_root=tmp_path)


# --- DB runner: 0-vs-NULL, isolation, idempotency ---------------------------

def make_db(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    rows = [("A", "laos", box(100, 15, 101, 16)),
            ("B", "laos", box(102, 15, 103, 16)),       # covered by extract, empty
            ("C", "vietnam", box(100, 15, 101, 16))]    # other country: untouched
    conn.executemany(
        "INSERT INTO zones (id, country, geom, strike_density, crater_evidence,"
        " exposure, priority_score, priority_rank) VALUES (?,?,?,?,?,?,?,?)",
        [(zid, country, json.dumps(mapping(shapely.MultiPolygon([geom]))),
          None, 1.5, None, 0.9, 1) for zid, country, geom in rows])
    conn.commit()
    conn.close()
    return path


def read_zones(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM zones ORDER BY id")]
    conn.close()
    return {r["id"]: r for r in rows}


def test_runner_writes_density_zero_not_null_and_is_idempotent(tmp_path):
    db = make_db(tmp_path)
    pbf = write_tiny_pbf(tmp_path / "tiny.osm.pbf")
    summary = exposure_country("laos", db_path=db, pbf_path=pbf)
    # 7 of 8 features land in A (incl. boundary hamlet + partial way); outside node in none.
    assert summary["zones"] == 2 and summary["features"] == 8
    assert summary["assigned"] == 7 and summary["outside"] == 1
    assert summary["partial_ways"] == 1 and summary["invalid_ways"] == 1
    assert summary["zones_with_exposure"] == 1 and summary["zones_zero"] == 1
    zones = read_zones(db)
    assert zones["A"]["exposure"] > 0
    assert zones["B"]["exposure"] == 0.0       # covered-but-empty: 0.0, not NULL
    assert zones["C"]["exposure"] is None     # other country never touched
    # Scoring-owned columns and other components untouched.
    assert zones["A"]["priority_score"] == 0.9 and zones["A"]["priority_rank"] == 1
    assert zones["A"]["crater_evidence"] == 1.5 and zones["A"]["strike_density"] is None
    first = read_zones(db)
    exposure_country("laos", db_path=db, pbf_path=pbf)
    assert read_zones(db) == first            # idempotent re-run


def test_runner_missing_extract_leaves_null(tmp_path):
    db = make_db(tmp_path)
    with pytest.raises(FileNotFoundError):
        exposure_country("laos", db_path=db, pbf_path=tmp_path / "missing.osm.pbf")
    assert all(z["exposure"] is None for z in read_zones(db).values())


def test_scoring_still_zero_with_exposure_but_no_thor(tmp_path):
    # Exposure alone cannot score a zone: strike_density NULL -> unscorable.
    db = make_db(tmp_path)
    exposure_country("laos", db_path=db, pbf_path=write_tiny_pbf(tmp_path / "t.osm.pbf"))
    summary = score_country("laos", db_path=db, now="2026-10-27T00:00:00+00:00")
    assert summary["scored"] == 0
    assert summary["null_components"] == {"strike_density": 2, "crater_evidence": 0,
                                          "exposure": 0}
