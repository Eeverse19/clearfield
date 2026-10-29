"""Match Barthelme KH-9 crater predictions to KH-9 photo frames.

Inputs
------
* ``data/clearfield.db`` -- SQLite table ``craters`` (id, country, source,
  geom, centroid, area_m2, circularity, confidence, crater_class). The
  ``centroid`` column is a GeoJSON Point in EPSG:4326 (``[lon, lat]``).
  ~541k rows are streamed in batches, never loaded all at once.
* ``data/kh9/{quang_tri,tri_border}/*-8mpp.tif`` -- georeferenced KH-9
  frames, EPSG:32648 (UTM 48N), 8 m/px (listed in ``data/kh9/summary.json``;
  this script discovers them by glob so new frames are picked up).

Outputs (in ``--out``, default ``data/kh9``)
--------------------------------------------
* ``bomb_coordinates.csv.gz`` -- one row per crater (see CSV_COLUMNS).
  ``kh9_frame``/``kh9_area`` and the pixel columns are empty when no frame
  covers the centroid. ``in_frame`` is ``true``/``false``.
* ``bomb_coordinates.geojson`` -- in-frame subset only, Point geometry
  ``[lon, lat]``, with the same properties as the CSV (typed values).
* ``kh9_match_summary.json`` -- totals, in-frame count/percent, per-frame
  and per-country counts, frame metadata and CRS notes.

Honesty label
-------------
These are Barthelme KH-9 crater *predictions* (bomb-impact crater
locations), NOT confirmed live-bomb / unexploded-ordnance locations.
Source ``confidence`` is NULL in the original predictions; no confidence
is invented here.

Limits
------
Frame choice prefers a frame where the centroid pixel is on valid
imagery (the frames are diagonal strips; ~24% of centroids fall on a
nodata corner of the first bounds-covering frame but on valid pixels
of another overlapping frame — measured 2026-10-28). ``frame_pixel_valid``
records the coarse-mask (16 px cells) result for the chosen frame.
The 8 m/px pixel reference locates the crater centroid in the photo;
the crater shape itself is only visible at 1 m/px. The 1 m/px pixel
columns are therefore *derived* (``col_1mpp = col_8mpp * 8``,
``row_1mpp = row_8mpp * 8``, ``derived_1mpp=true``): the 1 m/px frames
share each frame's extent at 8x resolution, but were not read here.
Published geolocation error for the source data is ~7--17.5 m, i.e.
~1--2 px at 8 m/px, so sub-pixel precision in the output should not be
over-interpreted.

Usage
-----
    python scripts/kh9_match.py [--out data/kh9] [--limit N]

Requires rasterio (frame bounds/transforms) and pyproj (EPSG:4326 ->
EPSG:32648). If pyproj is unavailable, rasterio.warp (GDAL) is used as
the coordinate transform fallback, e.g. under ``.venv-sam``.
"""

import argparse
import csv
import gzip
import json
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

try:
    import rasterio
    from rasterio.warp import transform as warp_transform
except ImportError:  # pragma: no cover - exercised only in broken envs
    rasterio = None
    warp_transform = None

try:
    from pyproj import Transformer
except ImportError:  # pragma: no cover - fallback path uses rasterio.warp
    Transformer = None

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "clearfield.db"
KH9_DIR = REPO_ROOT / "data" / "kh9"
SOURCE_CRS = "EPSG:4326"
TARGET_CRS = "EPSG:32648"  # UTM zone 48N, the KH-9 frames' CRS
TARGET_EPSG = 32648
HONESTY_LABEL = (
    "Barthelme KH-9 crater predictions (impact locations); not confirmed "
    "unexploded ordnance. Source confidence is NULL in the original predictions."
)
BATCH_SIZE = 5000
PROGRESS_EVERY = 100_000

CSV_COLUMNS = [
    "crater_id",
    "country",
    "lon",
    "lat",
    "utm_easting",
    "utm_northing",
    "area_m2",
    "circularity",
    "crater_class",
    "kh9_frame",
    "kh9_area",
    "pixel_col_8mpp",
    "pixel_row_8mpp",
    "pixel_col_1mpp_derived",
    "pixel_row_1mpp_derived",
    "in_frame",
    # Extra bookkeeping required alongside the columns above: how many
    # frames covered the point (the chosen frame is the first by area
    # name then filename), and that the 1 m/px pixels are derived.
    "all_frames",
    "frame_pixel_valid",
    "derived_1mpp",
]

MASK_SCALE = 16  # valid-mask cell size in 8 m/px pixels (~128 m)


@dataclass
class Frame:
    area: str
    filename: str
    path: Path
    crs: str
    bounds: tuple  # (left, bottom, right, top) in EPSG:32648
    transform: object  # rasterio Affine
    inv_transform: object  # inverse Affine
    width: int
    height: int
    valid_mask: object = None  # coarse bool array (MASK_SCALE px cells)

    def pixel_valid(self, col: float, row: float) -> bool:
        if self.valid_mask is None:
            return True
        r, c = int(row // MASK_SCALE), int(col // MASK_SCALE)
        return bool(0 <= r < self.valid_mask.shape[0]
                    and 0 <= c < self.valid_mask.shape[1]
                    and self.valid_mask[r, c])


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Match Barthelme crater centroids to KH-9 frames and "
                    "emit crater (impact) coordinates with pixel references.")
    parser.add_argument("--out", default="data/kh9",
                        help="output directory (default: data/kh9)")
    parser.add_argument("--limit", type=int, default=None,
                        help="only process the first N craters (by id)")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be >= 0")
    return args


def load_frames(kh9_dir):
    """Frame metadata via rasterio, sorted by area name then filename."""
    frames = []
    for path in sorted(kh9_dir.glob("*/*-8mpp.tif"),
                       key=lambda p: (p.parent.name, p.name)):
        with rasterio.open(path) as ds:
            crs = str(ds.crs) if ds.crs is not None else ""
            nodata = ds.nodata if ds.nodata is not None else -32768.0
            coarse = ds.read(1, out_shape=(max(1, ds.height // MASK_SCALE),
                                           max(1, ds.width // MASK_SCALE)))
            frames.append(Frame(
                valid_mask=coarse > (nodata + 1000),
                area=path.parent.name,
                filename=path.name,
                path=path,
                crs=crs,
                bounds=(float(ds.bounds.left), float(ds.bounds.bottom),
                        float(ds.bounds.right), float(ds.bounds.top)),
                transform=ds.transform,
                inv_transform=~ds.transform,
                width=int(ds.width),
                height=int(ds.height),
            ))
    return frames


def make_transformer():
    """Return (batch_transform(lons, lats) -> (xs, ys), description)."""
    if Transformer is not None:
        transformer = Transformer.from_crs(
            SOURCE_CRS, TARGET_CRS, always_xy=True)

        def batch(lons, lats):
            xs, ys = transformer.transform(lons, lats)
            return list(xs), list(ys)

        return batch, "pyproj Transformer EPSG:4326 -> EPSG:32648 (always_xy)"
    if warp_transform is not None:
        def batch(lons, lats):
            xs, ys = warp_transform(SOURCE_CRS, TARGET_CRS, lons, lats)
            return list(xs), list(ys)

        return batch, "rasterio.warp.transform EPSG:4326 -> EPSG:32648"
    return None, ""


def parse_centroid(text):
    """GeoJSON Point text -> (lon, lat), or None if unusable."""
    if not text:
        return None
    try:
        coords = json.loads(text)["coordinates"]
        return float(coords[0]), float(coords[1])
    except (ValueError, TypeError, KeyError, IndexError):
        return None


def fmt(value):
    """CSV cell: empty for None, full round-trip repr for floats."""
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return value


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if rasterio is None:
        print("error: rasterio is required but not installed "
              "(run with .venv-sam python or install rasterio)",
              file=sys.stderr)
        return 2
    if not DB_PATH.is_file():
        print(f"error: crater database not found: {DB_PATH}", file=sys.stderr)
        return 2
    if not KH9_DIR.is_dir():
        print(f"error: KH-9 directory not found: {KH9_DIR}", file=sys.stderr)
        return 2

    frames = load_frames(KH9_DIR)
    if not frames:
        print(f"error: no *-8mpp.tif KH-9 frames found under {KH9_DIR}",
              file=sys.stderr)
        return 2
    for frame in frames:
        if frame.crs and frame.crs != TARGET_CRS:
            print(f"warning: frame {frame.filename} CRS is {frame.crs}, "
                  f"expected {TARGET_CRS}; its pixel coordinates assume "
                  f"{TARGET_CRS}", file=sys.stderr)

    transform_batch, transform_desc = make_transformer()
    if transform_batch is None:
        print("error: neither pyproj nor rasterio.warp is available for "
              "EPSG:4326 -> EPSG:32648 transformation", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = Path.cwd() / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "bomb_coordinates.csv.gz"
    geojson_path = out_dir / "bomb_coordinates.geojson"
    summary_path = out_dir / "kh9_match_summary.json"

    print(f"{len(frames)} KH-9 frames loaded from {KH9_DIR} "
          f"({transform_desc})", flush=True)

    total = 0
    in_frame_count = 0
    valid_pixel_count = 0
    skipped_centroid = 0
    per_frame_counts = Counter()
    per_country_counts = Counter()
    per_country_in_frame = Counter()
    next_progress = PROGRESS_EVERY

    sql = ("SELECT id, country, centroid, area_m2, circularity, crater_class "
           "FROM craters ORDER BY id")
    if args.limit is not None:
        sql += f" LIMIT {int(args.limit)}"

    con = sqlite3.connect(DB_PATH)
    try:
        cursor = con.cursor()
        cursor.execute(sql)
        with gzip.open(csv_path, "wt", newline="", encoding="utf-8") as gz, \
                geojson_path.open("w", encoding="utf-8") as gj:
            writer = csv.writer(gz)
            writer.writerow(CSV_COLUMNS)
            gj.write('{"type": "FeatureCollection", "name": '
                     '"bomb_coordinates", "features": [\n')
            geojson_first = True

            while True:
                rows = cursor.fetchmany(BATCH_SIZE)
                if not rows:
                    break

                # Batch-transform this chunk's centroids to EPSG:32648.
                parsed = [parse_centroid(r[2]) for r in rows]
                lons = [p[0] if p else 0.0 for p in parsed]
                lats = [p[1] if p else 0.0 for p in parsed]
                xs, ys = transform_batch(lons, lats)

                for row, lonlat, easting, northing in zip(
                        rows, parsed, xs, ys):
                    (crater_id, country, _centroid, area_m2,
                     circularity, crater_class) = row
                    total += 1
                    per_country_counts[country or ""] += 1

                    lon = lat = utm_e = utm_n = None
                    covering = []
                    if lonlat is None:
                        skipped_centroid += 1
                    else:
                        lon, lat = lonlat
                        utm_e, utm_n = float(easting), float(northing)
                        for frame in frames:
                            left, bottom, right, top = frame.bounds
                            if not (left <= utm_e <= right
                                    and bottom <= utm_n <= top):
                                continue
                            col, row_px = frame.inv_transform * (utm_e, utm_n)
                            if 0 <= col < frame.width and 0 <= row_px < frame.height:
                                covering.append((frame, float(col), float(row_px)))

                    # Prefer the first covering frame where the pixel is
                    # on valid imagery (frames are diagonal nodata strips);
                    # fall back to the first covering frame and flag it.
                    chosen = next((c for c in covering
                                   if c[0].pixel_valid(c[1], c[2])), None)
                    frame_pixel_valid = chosen is not None
                    if chosen is None and covering:
                        chosen = covering[0]
                    in_frame = chosen is not None
                    if in_frame:
                        in_frame_count += 1
                        if frame_pixel_valid:
                            valid_pixel_count += 1
                        per_frame_counts[chosen[0].filename] += 1
                        per_country_in_frame[country or ""] += 1

                    record = {
                        "crater_id": crater_id,
                        "country": country or "",
                        "lon": lon,
                        "lat": lat,
                        "utm_easting": utm_e,
                        "utm_northing": utm_n,
                        "area_m2": area_m2,
                        "circularity": circularity,
                        "crater_class": crater_class,
                        "kh9_frame": chosen[0].filename if chosen else "",
                        "kh9_area": chosen[0].area if chosen else "",
                        "pixel_col_8mpp": chosen[1] if chosen else None,
                        "pixel_row_8mpp": chosen[2] if chosen else None,
                        "pixel_col_1mpp_derived":
                            chosen[1] * 8 if chosen else None,
                        "pixel_row_1mpp_derived":
                            chosen[2] * 8 if chosen else None,
                        "in_frame": in_frame,
                        "all_frames": len(covering),
                        "frame_pixel_valid": frame_pixel_valid if in_frame else False,
                        # 1 m/px pixels exist only as a derivation from the
                        # 8 m/px reference, and only when in a frame.
                        "derived_1mpp": in_frame,
                    }
                    writer.writerow([
                        fmt(record[c]) if not isinstance(record[c], bool)
                        else str(record[c]).lower()
                        for c in CSV_COLUMNS
                    ])

                    if in_frame:
                        feature = {
                            "type": "Feature",
                            "geometry": {"type": "Point",
                                         "coordinates": [lon, lat]},
                            "properties": record,
                        }
                        if not geojson_first:
                            gj.write(",\n")
                        geojson_first = False
                        gj.write(json.dumps(feature))

                    if total >= next_progress:
                        print(f"  {total} craters processed "
                              f"({in_frame_count} in frame)...", flush=True)
                        next_progress += PROGRESS_EVERY

            gj.write("\n]}\n")
    finally:
        con.close()

    percent = (100.0 * in_frame_count / total) if total else 0.0
    summary = {
        "label": HONESTY_LABEL,
        "honesty_label": HONESTY_LABEL,
        "total_craters": total,
        "total": total,
        "limit": args.limit,
        "in_frame_count": in_frame_count,
        "in_frame": in_frame_count,
        "in_frame_percent": round(percent, 4),
        "assigned_on_valid_pixel": valid_pixel_count,
        "assigned_on_valid_pixel_note": (
            "Chosen frame is the first covering frame (area, filename) "
            "whose coarse valid mask (16 px cells, nodata=-32768) contains "
            "the centroid; frame_pixel_valid=false marks the fallback to a "
            "bounds-covering frame whose pixel is on a nodata strip."),
        "out_of_frame_count": total - in_frame_count,
        "skipped_unusable_centroid": skipped_centroid,
        "per_frame_counts": {
            f.filename: per_frame_counts.get(f.filename, 0) for f in frames
        },
        "per_country_counts": dict(sorted(per_country_counts.items())),
        "per_country_in_frame_counts": dict(
            sorted(per_country_in_frame.items())),
        "crs": {
            "centroid_source": SOURCE_CRS,
            "frame": TARGET_CRS,
            "utm_zone": "48N",
            "transform": transform_desc,
        },
        "crs_notes": (
            f"Crater centroids are stored as GeoJSON Points in {SOURCE_CRS} "
            f"([lon, lat]) and were transformed to {TARGET_CRS} (UTM 48N), "
            f"the CRS of every KH-9 8 m/px frame, via {transform_desc}. "
            "Pixel (col, row) are fractional coordinates from the inverse "
            "of each frame's rasterio affine. When frames overlap, the "
            "first frame sorted by area name then filename is recorded in "
            "kh9_frame and the number of covering frames in all_frames."
        ),
        "frames": [
            {
                "frame": f.filename,
                "kh9_frame": f.filename,
                "area": f.area,
                "kh9_area": f.area,
                "path": f.path.relative_to(REPO_ROOT).as_posix(),
                "crs": f.crs,
                "bounds_epsg32648": {
                    "left": f.bounds[0], "bottom": f.bounds[1],
                    "right": f.bounds[2], "top": f.bounds[3],
                },
                "width_px": f.width,
                "height_px": f.height,
                "transform": list(f.transform)[:6],
                "count": per_frame_counts.get(f.filename, 0),
            }
            for f in frames
        ],
        "derived_1mpp": True,
        "derived_1mpp_note": (
            "pixel_col_1mpp_derived = pixel_col_8mpp * 8 and "
            "pixel_row_1mpp_derived = pixel_row_8mpp * 8 (derived_1mpp=true "
            "for in-frame craters). The 1 m/px frames share each frame's "
            "extent at 8x resolution but were not read; crater shape is "
            "only visible at 1 m/px, while the 8 m/px reference locates "
            "the centroid. Source geolocation error is ~7-17.5 m "
            "(~1-2 px at 8 m/px)."
        ),
        "outputs": {
            "csv_gz": csv_path.name,
            "csv_columns": CSV_COLUMNS,
            "geojson": geojson_path.name,
            "geojson_scope": "in-frame craters only",
            "summary": summary_path.name,
        },
    }
    # per_frame mirrors per_frame_counts as a list for convenience.
    summary["per_frame"] = summary["frames"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"done: {total} craters, {in_frame_count} in frame "
          f"({percent:.2f}%) -> {csv_path}, {geojson_path}, {summary_path}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
