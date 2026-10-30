"""Distill DB crater centroids into per-country point files for the GUI.

Usage: python scripts/make_crater_points.py

Reads craters.centroid (GeoJSON Point, EPSG:4326) from
data/clearfield.db and writes, per crater country:
  data/kh9/crater_points_{country}.f32  little-endian float32 (lon, lat)
  data/kh9/crater_points_manifest.json  counts by country

These are Barthelme KH-9 crater *predictions* (impact locations), not
confirmed unexploded ordnance — the GUI labels them that way. Polygons
stay in the DB / bomb_coordinates.geojson; centroids are what a
country-scale map can draw. Source detail: docs/kh9-coordinates.md.
"""

import array
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "clearfield.db"
OUT_DIR = REPO_ROOT / "data" / "kh9"


def main() -> int:
    if not DB_PATH.exists():
        print(f"error: {DB_PATH} not found (run scripts/seed_db.py)", file=sys.stderr)
        return 2
    con = sqlite3.connect(DB_PATH)
    try:
        countries = [r[0] for r in con.execute(
            "SELECT DISTINCT country FROM craters ORDER BY country")]
        manifest = {"source": "craters.centroid in data/clearfield.db "
                              "(Barthelme KH-9 predictions; impact locations, "
                              "not confirmed UXO)", "countries": {}}
        for country in countries:
            pts = array.array("f")
            n = 0
            for (text,) in con.execute(
                    "SELECT centroid FROM craters WHERE country = ?", (country,)):
                lon, lat = json.loads(text)["coordinates"]
                pts.extend((float(lon), float(lat)))
                n += 1
            out = OUT_DIR / f"crater_points_{country}.f32"
            with out.open("wb") as fh:
                pts.tofile(fh)
            manifest["countries"][country] = {
                "points": n, "file": out.name,
                "bytes": out.stat().st_size}
            print(f"{country}: {n:,} crater centroids -> {out.name}")
    finally:
        con.close()
    (OUT_DIR / "crater_points_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"manifest -> {OUT_DIR / 'crater_points_manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
