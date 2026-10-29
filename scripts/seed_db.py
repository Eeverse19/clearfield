"""Seed the local SQLite DB from downloaded data. See seed_db.ps1/.sh wrappers.

What this seeds today (everything reproducible without API keys; THOR
strike_density is seeded separately by scripts/seed_thor.py):
- zones: GADM 4.1 admin-1 polygons for every country profile (laos, cambodia,
  AND vietnam - 511,541 of the craters are Vietnamese; list_countries() drives
  seeding, demo scope does not). Zones are UPSERTED on (id): re-runs update
  geometry/name/country only and never reset surveyed_status, score
  components, or finds. strike_density comes from scripts/seed_thor.py
  and exposure from pipelines/osm_exposure.py, so no zone is rankable
  after this seed alone - scoring correctly returns 0.
- craters: Barthelme predicted crater polygons (predictions.zip), transformed
  EPSG:32648 -> EPSG:4326 (CRS asserted from each file's crs member).
  area_m2/circularity/centroid computed per polygon; confidence NULL (source
  publishes none); crater_class = source properties.value (1-5). Country is
  the GADM zone covering the centroid (largest overlap, then smallest id, on
  multi-hit); craters in no seeded country are counted, never guessed.
- zones.crater_evidence: seeded craters per km2, only for zones intersecting
  a study area's crater convex hull AND containing at least one crater. It is
  a lower bound where a zone is only partly covered by KH-9 scenes, and NULL
  (not 0) elsewhere: no coverage must never read as no craters. Replacing the
  hull with real scene footprints + a coverage fraction is still open
  (WORKFLOW_SYNTHESIS.md S2-S4/U7).

Idempotent for zones/finds; craters of this source are replaced each run.
Ends with reconciliation counters + integrity_check, and fails (exit 1)
before any DELETE if a profile GADM file or predictions.zip is missing.
Runtime observed 2026-10-26: ~65 min for 541,398 features on this laptop.
First run seeded 541,397 craters (1 skipped) into 106 zones.
"""

import json
import math
import sqlite3
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from pyproj import Geod, Transformer  # noqa: E402
from shapely import MultiPoint, STRtree  # noqa: E402
from shapely.geometry import MultiPolygon, mapping, shape  # noqa: E402

from backend.app.config import LOCAL_DB_PATH, REPO_ROOT  # noqa: E402
from backend.app.profiles import list_countries  # noqa: E402

SOURCE = "barthelme_predictions"
STUDY_AREAS = ("quang_tri", "tri_border_area")
EXPECTED_CRS = "EPSG::32648"
TO_4326 = Transformer.from_crs(32648, 4326, always_xy=True)
GEOD = Geod(ellps="WGS84")


def zone_hits(tree: STRtree, centroid) -> list:
    """Indices of zones the centroid falls in.

    Predicate direction matters: STRtree.query evaluates
    predicate(input, candidate), so this must be "within" (centroid
    within zone). The original "covers" asked whether the point covers
    the zone -- always false, which silently seeded 0 craters with a
    reconciled total (found 2026-10-28, shapely 2.2.0).
    """
    return list(tree.query(centroid, predicate="within"))


def to_4326(geom):
    return shapely.transform(
        geom, lambda c: np.column_stack(TO_4326.transform(c[:, 0], c[:, 1])))


def iter_features(zf: zipfile.ZipFile, member: str, counters: dict):
    """Stream one-feature-per-line GeoJSON, counting anything unparsable."""
    with zf.open(member) as raw:
        for line in raw:
            line = line.strip().rstrip(b",")
            if not line.startswith(b"{") or line in (b"{", b"}"):
                continue  # collection header/footer lines (incl. the lone "{")
            try:
                feat = json.loads(line)
            except json.JSONDecodeError:
                counters["unparsed"] += 1
                continue
            if feat.get("type") != "Feature":
                counters["unparsed"] += 1
                continue
            counters["features"] += 1
            yield feat


def assert_crs(zf: zipfile.ZipFile, member: str) -> None:
    with zf.open(member) as raw:
        head = raw.read(2000).decode("utf-8", "replace")
    if EXPECTED_CRS not in head:
        raise ValueError(f"{member}: expected crs {EXPECTED_CRS}, head was: {head[:200]!r}")


def load_gadm_zones() -> list[dict]:
    zones, missing = [], []
    for profile in list_countries():
        code = profile["boundaries"].get("country_code")
        path = REPO_ROOT / "data" / "gadm" / f"gadm41_{code}_1.json"
        if not path.exists():
            missing.append(str(path.relative_to(REPO_ROOT)))
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for feat in data["features"]:
            geom = shapely.make_valid(shape(feat["geometry"]))
            if geom.geom_type == "Polygon":
                geom = MultiPolygon([geom])
            assert geom.geom_type == "MultiPolygon" and geom.is_valid, feat["properties"]
            zones.append({
                "id": feat["properties"]["GID_1"],
                "country": profile["id"],
                "admin_name": feat["properties"]["NAME_1"],
                "geom": geom,
                "area_km2": abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6,
            })
    if missing:  # fail hard: a partial country set corrupts by omission
        raise FileNotFoundError(f"missing GADM files (download them first): {missing}")
    return zones


def ensure_crater_class_column(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(craters)")}
    if "crater_class" not in cols:
        conn.execute("ALTER TABLE craters ADD COLUMN crater_class INTEGER")


INSERT_CRATER = (
    "INSERT INTO craters (id, country, source, geom, centroid, area_m2,"
    " circularity, confidence, tile_id, crater_class) VALUES (?,?,?,?,?,?,?,?,?,?)"
)


def main() -> int:
    zip_path = REPO_ROOT / "data" / "barthelme" / "predictions.zip"
    if not zip_path.exists():
        print("predictions.zip missing: run scripts/download_data.ps1 predictions.zip first",
              file=sys.stderr)
        return 1
    try:
        zones = load_gadm_zones()
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    db_path = LOCAL_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript((REPO_ROOT / "db" / "schema.local.sql").read_text(encoding="utf-8"))
    ensure_crater_class_column(conn)
    tree = STRtree([z["geom"] for z in zones])

    conn.executemany(
        "INSERT INTO zones (id, country, admin_name, geom) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(id) DO UPDATE SET country=excluded.country,"
        " admin_name=excluded.admin_name, geom=excluded.geom",
        [(z["id"], z["country"], z["admin_name"], json.dumps(mapping(z["geom"])))
         for z in zones])
    conn.execute("DELETE FROM craters WHERE source = ?", (SOURCE,))
    print(f"zones upserted: {len(zones)} ({', '.join(sorted({z['country'] for z in zones}))})")

    counts = {z["id"]: 0 for z in zones}
    hulls, totals = [], {"seeded": 0, "invalid": 0, "outside": 0, "multi_hit": 0,
                          "circ_over_1": 0, "unparsed": 0, "features": 0}
    batch: list[tuple] = []
    with zipfile.ZipFile(zip_path) as zf:
        for area in STUDY_AREAS:
            member = f"predictions/{area}/crater_polygons.geojson"
            assert_crs(zf, member)
            area_counters = {"features": 0, "unparsed": 0}
            centroids = []
            for i, feat in enumerate(iter_features(zf, member, area_counters)):
                geom = shapely.make_valid(shape(feat["geometry"]))
                if geom.is_empty or geom.area == 0 or geom.geom_type not in ("Polygon", "MultiPolygon"):
                    totals["invalid"] += 1
                    continue
                poly_utm = max(geom.geoms, key=lambda g: g.area) \
                    if geom.geom_type == "MultiPolygon" else geom
                centroid = to_4326(poly_utm.centroid)
                centroids.append(centroid)  # coverage uses ALL source craters
                hits = zone_hits(tree, centroid)
                if not hits:
                    totals["outside"] += 1
                    continue
                poly4326 = to_4326(poly_utm)
                if len(hits) > 1:
                    totals["multi_hit"] += 1
                    hits.sort(key=lambda j: (-poly4326.intersection(zones[j]["geom"]).area,
                                             zones[j]["id"]))
                zone = zones[hits[0]]
                counts[zone["id"]] += 1
                circ = 4 * math.pi * poly_utm.area / (poly_utm.length ** 2)
                if circ > 1.0:
                    totals["circ_over_1"] += 1
                value = feat.get("properties", {}).get("value")
                batch.append((f"barthelme:{area}:{i}", zone["country"], SOURCE,
                              json.dumps(mapping(poly4326)), json.dumps(mapping(centroid)),
                              poly_utm.area, min(circ, 1.0), None, None,
                              int(value) if value is not None else None))
                totals["seeded"] += 1
                if len(batch) >= 5000:
                    conn.executemany(INSERT_CRATER, batch)
                    batch.clear()
            totals["features"] += area_counters["features"]
            totals["unparsed"] += area_counters["unparsed"]
            if centroids:
                hulls.append(MultiPoint(centroids).convex_hull)
            print(f"{area}: features {area_counters['features']}, craters so far {totals['seeded']}",
                  flush=True)
    if batch:
        conn.executemany(INSERT_CRATER, batch)
    if totals["unparsed"]:
        print(f"FAIL: {totals['unparsed']} unparsed feature lines", file=sys.stderr)
        conn.rollback()
        conn.close()
        return 1

    covered = 0
    for z in zones:
        evidence = None
        if counts[z["id"]] > 0 and hulls and any(z["geom"].intersects(h) for h in hulls):
            evidence = counts[z["id"]] / z["area_km2"] if z["area_km2"] else None
            covered += 1 if evidence is not None else 0
        conn.execute("UPDATE zones SET crater_evidence = ? WHERE id = ?", (evidence, z["id"]))
    conn.commit()

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    db_craters = conn.execute("SELECT COUNT(*) FROM craters WHERE source = ?", (SOURCE,)).fetchone()[0]
    conn.close()
    reconciled = totals["features"] == totals["seeded"] + totals["invalid"] + totals["outside"]
    print(f"reconciliation: features {totals['features']} = seeded {totals['seeded']} + invalid "
          f"{totals['invalid']} + outside {totals['outside']} -> {'ok' if reconciled else 'MISMATCH'}; "
          f"db craters {db_craters}; multi-hit {totals['multi_hit']}; circ>1 {totals['circ_over_1']}")
    print(f"zones with crater_evidence: {covered}/{len(zones)}; integrity {integrity}; fk violations {len(fk)}")
    print(f"db: {db_path}")
    return 0 if (reconciled and integrity == "ok" and not fk
                 and db_craters == totals["seeded"]) else 1


if __name__ == "__main__":
    sys.exit(main())
