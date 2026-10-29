"""Visual QA overlays: Barthelme crater centroids on KH-9 8 m/px frames.

Usage:
    python scripts/kh9_qa_overlays.py [--out data/kh9/qa] [--windows 6]
                                      [--window-px 1024]

Finds the densest crater windows in the KH-9 frames under
``data/kh9/quang_tri/*-8mpp.tif`` and ``data/kh9/tri_border/*-8mpp.tif``
(EPSG:32648, 8 m/px), renders each window as a percentile-stretched
grayscale PNG, and draws every crater centroid from the ``craters``
table of ``data/clearfield.db`` that falls inside the window as a
small red circle. Centroids are stored as GeoJSON Points in
EPSG:4326 (``[lon, lat]``) and are projected to EPSG:32648 for the
overlay. Each PNG gets a sidecar ``.json`` (frame path, window pixel
offsets, UTM bounds, crater count and ids), and an ``index.json``
summarises all rendered windows.

Note on scale: at 8 m/px a 25 m2 crater is sub-pixel to ~1 px, so the
red markers show where coordinates fall in dense crater fields;
individual crater shapes need the 1 m/px frames. This QA checks
registration/density alignment -- that markers cluster on disturbed,
texture-dense ground rather than landing offset in undisturbed
terrain -- not individual crater visibility.
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image, ImageDraw
from rasterio.enums import Resampling
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window, bounds as window_bounds

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "clearfield.db"
KH9_ROOT = REPO_ROOT / "data" / "kh9"
AREAS = ("quang_tri", "tri_border")
TARGET_EPSG = 32648
MARKER_RADIUS_PX = 2
# KH-9 frames are rotated photographic strips inside a north-up raster:
# much of each frame's rectangular bounds is nodata. Only windows that
# actually contain photographic coverage make sense for visual QA.
MIN_VALID_FRACTION = 0.90
COARSE_SCALE_PX = 32  # frame pixels per pixel of the coverage overview


def load_craters(db_path: Path):
    """Return (ids, xs, ys) with centroids projected to EPSG:32648."""
    if not db_path.exists():
        raise SystemExit(f"crater database not found: {db_path}")
    ids: list[str] = []
    lonlat: list[tuple[float, float]] = []
    with sqlite3.connect(db_path) as con:
        rows = con.execute(
            "SELECT id, centroid FROM craters WHERE centroid IS NOT NULL"
        )
        for crater_id, centroid in rows:
            try:
                geom = json.loads(centroid)
                lon, lat = geom["coordinates"][:2]
                lonlat.append((float(lon), float(lat)))
                ids.append(str(crater_id))
            except (ValueError, TypeError, KeyError, IndexError):
                continue
    if not lonlat:
        raise SystemExit(f"no usable crater centroids in {db_path}")
    coords = np.asarray(lonlat, dtype=np.float64)
    # rasterio.warp (PROJ under the hood); avoids a hard pyproj dependency,
    # which is not present in every project venv.
    xs, ys = warp_transform("EPSG:4326", f"EPSG:{TARGET_EPSG}",
                            coords[:, 0].tolist(), coords[:, 1].tolist())
    return ids, np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)


def find_frames() -> list[tuple[str, Path]]:
    frames: list[tuple[str, Path]] = []
    for area in AREAS:
        area_dir = KH9_ROOT / area
        for path in sorted(area_dir.glob("*-8mpp.tif")):
            frames.append((area, path))
    if not frames:
        raise SystemExit(f"no *-8mpp.tif frames under {KH9_ROOT}")
    return frames


def pixel_coords(dataset, xs: np.ndarray, ys: np.ndarray):
    """Projected (EPSG:32648) points -> fractional (col, row) in a frame."""
    inv = ~dataset.transform
    cols, rows = inv * (xs, ys)
    return np.asarray(cols, dtype=np.float64), np.asarray(rows, dtype=np.float64)


def candidate_windows(frames, ids, xs, ys, window_px: int) -> list[dict]:
    """Coarse 2D histogram (window-px bins per frame) -> ranked candidates."""
    candidates: list[dict] = []
    for area, frame_path in frames:
        with rasterio.open(frame_path) as ds:
            if ds.crs is None or ds.crs.to_epsg() != TARGET_EPSG:
                print(f"skip {frame_path.name}: CRS is {ds.crs}, "
                      f"expected EPSG:{TARGET_EPSG}", file=sys.stderr)
                continue
            left, bottom, right, top = ds.bounds
            inside = np.flatnonzero(
                (xs >= left) & (xs < right) & (ys > bottom) & (ys <= top)
            )
            if inside.size == 0:
                continue
            cols, rows = pixel_coords(ds, xs[inside], ys[inside])
            in_frame = (cols >= 0) & (cols < ds.width) & (rows >= 0) & (rows < ds.height)
            inside, cols, rows = inside[in_frame], cols[in_frame], rows[in_frame]
            if inside.size == 0:
                continue
            bin_cols = (cols // window_px).astype(np.int64)
            bin_rows = (rows // window_px).astype(np.int64)
            n_bin_cols = int(ds.width // window_px + 1)
            keys = bin_rows * n_bin_cols + bin_cols
            uniq_keys, counts = np.unique(keys, return_counts=True)
            # Coarse photographic-coverage mask (see MIN_VALID_FRACTION):
            # a decimated read, so each histogram bin maps to a block of
            # COARSE_SCALE_PX-wide coarse pixels whose valid fraction
            # approximates the full-resolution one.
            scale = min(COARSE_SCALE_PX, window_px)
            out_w = max(1, (ds.width + scale - 1) // scale)
            out_h = max(1, (ds.height + scale - 1) // scale)
            coarse = ds.read(1, out_shape=(out_h, out_w),
                             resampling=Resampling.nearest)
            valid_coarse = np.isfinite(coarse)
            if ds.nodata is not None:
                valid_coarse &= coarse != ds.nodata
            for key, count in zip(uniq_keys.tolist(), counts.tolist()):
                bin_row, bin_col = divmod(key, n_bin_cols)
                col_off = int(bin_col * window_px)
                row_off = int(bin_row * window_px)
                width = int(min(window_px, ds.width - col_off))
                height = int(min(window_px, ds.height - row_off))
                if width <= 0 or height <= 0:
                    continue
                cr0, cr1 = row_off // scale, (row_off + height + scale - 1) // scale
                cc0, cc1 = col_off // scale, (col_off + width + scale - 1) // scale
                block = valid_coarse[cr0:cr1, cc0:cc1]
                valid_fraction = float(block.mean()) if block.size else 0.0
                if valid_fraction < MIN_VALID_FRACTION:
                    continue
                win = Window(col_off, row_off, width, height)
                w_left, w_bottom, w_right, w_top = window_bounds(win, ds.transform)
                candidates.append({
                    "area": area,
                    "frame_path": frame_path,
                    "frame": frame_path.stem,
                    "col_off": col_off,
                    "row_off": row_off,
                    "width": width,
                    "height": height,
                    "count": int(count),
                    "valid_fraction_coarse": valid_fraction,
                    "utm_bounds": {
                        "left": float(w_left),
                        "bottom": float(w_bottom),
                        "right": float(w_right),
                        "top": float(w_top),
                    },
                })
    # Densest first; deterministic tie-breaks.
    candidates.sort(key=lambda c: (-c["count"], c["area"], c["frame"],
                                   c["row_off"], c["col_off"]))
    return candidates


def rectangles_overlap(a: dict, b: dict) -> bool:
    ab, bb = a["utm_bounds"], b["utm_bounds"]
    return not (ab["right"] <= bb["left"] or bb["right"] <= ab["left"]
                or ab["top"] <= bb["bottom"] or bb["top"] <= ab["bottom"])


def select_windows(candidates: list[dict], n_windows: int) -> list[dict]:
    """Top-N non-overlapping windows, spread across frames where possible.

    Greedy passes cap how many windows a single frame may contribute
    (1 per frame first, then 2, ...), so a single very dense frame
    cannot monopolise the QA set when other frames have dense windows.
    """
    selected: list[dict] = []
    selected_ids: set[int] = set()
    per_frame: Counter = Counter()
    max_per_frame = 1
    while len(selected) < n_windows:
        progressed = False
        for cand in candidates:
            if len(selected) >= n_windows:
                break
            if id(cand) in selected_ids:
                continue
            frame_key = str(cand["frame_path"])
            if per_frame[frame_key] >= max_per_frame:
                continue
            if any(rectangles_overlap(cand, chosen) for chosen in selected):
                continue
            selected.append(cand)
            selected_ids.add(id(cand))
            per_frame[frame_key] += 1
            progressed = True
        if not progressed:
            max_per_frame += 1
            if max_per_frame > n_windows:
                break
    return selected


def craters_in_window(dataset, cand: dict, ids, xs, ys):
    """Crater (id, dx, dy) for centroids inside the candidate window."""
    b = cand["utm_bounds"]
    inside = np.flatnonzero(
        (xs >= b["left"]) & (xs < b["right"])
        & (ys > b["bottom"]) & (ys <= b["top"])
    )
    if inside.size == 0:
        return []
    cols, rows = pixel_coords(dataset, xs[inside], ys[inside])
    dx = cols - cand["col_off"]
    dy = rows - cand["row_off"]
    in_window = (dx >= 0) & (dx < cand["width"]) & (dy >= 0) & (dy < cand["height"])
    return [(ids[int(i)], float(x), float(y))
            for i, x, y in zip(inside[in_window], dx[in_window], dy[in_window])]


def render_window(cand: dict, ids, xs, ys, out_dir: Path) -> dict:
    frame_path: Path = cand["frame_path"]
    with rasterio.open(frame_path) as ds:
        win = Window(cand["col_off"], cand["row_off"], cand["width"], cand["height"])
        arr = ds.read(1, window=win).astype(np.float64)
        points = craters_in_window(ds, cand, ids, xs, ys)
        nodata = ds.nodata

    valid = np.isfinite(arr)
    if nodata is not None:
        valid &= arr != nodata
    if valid.any():
        lo, hi = (float(v) for v in np.percentile(arr[valid], (2, 98)))
        if hi <= lo:
            hi = lo + 1.0
        gray = np.clip((arr - lo) / (hi - lo) * 255.0, 0, 255)
    else:
        gray = np.zeros(arr.shape, dtype=np.float64)
    gray[~valid] = 0
    image = Image.fromarray(gray.astype(np.uint8), mode="L").convert("RGB")
    draw = ImageDraw.Draw(image)
    r = MARKER_RADIUS_PX
    for _crater_id, dx, dy in points:
        draw.ellipse((dx - r, dy - r, dx + r, dy + r),
                     outline=(255, 0, 0), width=1)

    png_name = (f"{cand['area']}_{cand['frame']}_"
                f"{cand['col_off']}_{cand['row_off']}.png")
    png_path = out_dir / png_name
    image.save(png_path)

    try:
        frame_ref = frame_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        frame_ref = str(frame_path)
    metadata = {
        "png": png_name,
        "area": cand["area"],
        "frame": cand["frame"],
        "frame_path": frame_ref,
        "crs": f"EPSG:{TARGET_EPSG}",
        "window": {
            "col_off": cand["col_off"],
            "row_off": cand["row_off"],
            "width_px": cand["width"],
            "height_px": cand["height"],
        },
        "window_utm_bounds": cand["utm_bounds"],
        "valid_pixel_fraction": round(float(valid.mean()), 4) if valid.size else 0.0,
        "crater_count": len(points),
        "crater_ids": [crater_id for crater_id, _dx, _dy in points],
    }
    sidecar_path = out_dir / f"{png_path.stem}.json"
    sidecar_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render dense-crater KH-9 windows with centroid overlays "
                    "for visual registration QA.")
    parser.add_argument("--out", default=None,
                        help="output directory (default: data/kh9/qa)")
    parser.add_argument("--windows", type=int, default=6,
                        help="number of dense windows to render (default: 6)")
    parser.add_argument("--window-px", type=int, default=1024,
                        help="window size in pixels (default: 1024)")
    args = parser.parse_args(argv)
    if args.windows < 1:
        parser.error("--windows must be >= 1")
    if args.window_px < 16:
        parser.error("--window-px must be >= 16")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out) if args.out is not None else REPO_ROOT / "data" / "kh9" / "qa"
    if not out_dir.is_absolute():
        out_dir = (Path.cwd() / out_dir)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"loading crater centroids from {DB_PATH} ...", flush=True)
    ids, xs, ys = load_craters(DB_PATH)
    print(f"  {len(ids)} craters projected to EPSG:{TARGET_EPSG}", flush=True)

    frames = find_frames()
    print(f"  {len(frames)} KH-9 8 m/px frames in {len(AREAS)} areas", flush=True)

    candidates = candidate_windows(frames, ids, xs, ys, args.window_px)
    if not candidates:
        raise SystemExit("no crater-bearing windows found in any frame")
    selected = select_windows(candidates, args.windows)
    print(f"  {len(candidates)} crater-bearing {args.window_px}px bins with "
          f">= {MIN_VALID_FRACTION:.0%} photographic coverage; "
          f"rendering top {len(selected)} non-overlapping windows", flush=True)

    index_entries = []
    for cand in selected:
        metadata = render_window(cand, ids, xs, ys, out_dir)
        index_entries.append(metadata)
        b = metadata["window_utm_bounds"]
        print(f"{metadata['png']}: {metadata['crater_count']} craters "
              f"(frame {metadata['frame']}, col={cand['col_off']}, "
              f"row={cand['row_off']}, UTM left={b['left']:.0f}, "
              f"top={b['top']:.0f}, "
              f"valid={metadata['valid_pixel_fraction']:.1%})", flush=True)

    index = {
        "source_db": DB_PATH.relative_to(REPO_ROOT).as_posix(),
        "frames_root": KH9_ROOT.relative_to(REPO_ROOT).as_posix(),
        "crs": f"EPSG:{TARGET_EPSG}",
        "window_px": args.window_px,
        "windows_requested": args.windows,
        "windows_rendered": len(index_entries),
        "windows": index_entries,
    }
    (out_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"done -> {out_dir} ({len(index_entries)} PNGs + sidecars, index.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
