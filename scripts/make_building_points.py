"""Distill Microsoft footprint shards into centroid point files for the GUI.

Usage: python scripts/make_building_points.py --country laos|cambodia|vietnam

Reads the GeoJSONL shards cached by pipelines/building_exposure.py
(downloading them first if needed) and writes, per country:
  data/buildings/{Location}/centroids.f32   little-endian float32
                                            (lon, lat) pairs, EPSG:4326
  data/buildings/{Location}/points_manifest.json  count + source note

The GUI's /buildings endpoint serves bbox-filtered slices of this
file; centroids (not polygons) are what a country-scale map can draw.
Building polygons remain in the shards for zone-density work.
"""

import argparse
import array
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.building_exposure import (  # noqa: E402
    BUILDINGS_DIR, LOCATIONS, download_shards, iter_centroids)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--country", required=True, choices=sorted(LOCATIONS))
    args = ap.parse_args(argv)

    location = LOCATIONS[args.country]
    dest_dir = BUILDINGS_DIR / location
    shards = download_shards(args.country)
    points = array.array("f")
    for lon, lat in iter_centroids(shards):
        points.extend((lon, lat))
    out = dest_dir / "centroids.f32"
    with out.open("wb") as fh:
        points.tofile(fh)
    count = len(points) // 2
    manifest = {
        "country": args.country, "location": location,
        "points": count, "file": out.name, "format": "float32-le (lon, lat) pairs",
        "source": "Microsoft Global ML Building Footprints centroids (ODbL 1.0)",
        "shards": len(shards),
    }
    (dest_dir / "points_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{args.country}: {count:,} centroids -> {out} "
          f"({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
