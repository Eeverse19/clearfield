"""Sentinel-2 L2A scene -> georeferenced RGB chips for SAM (pilot).

Pipeline contract:
- Selects ONE Sentinel-2 L2A scene intersecting the country profile's
  demo zone (``demo_zone_id`` in the GADM admin-1 file under data/gadm/,
  downloaded from the same GADM source as scripts/download_data.py) via
  Earth Search STAC -- the endpoint behind
  https://registry.opendata.aws/sentinel-2/. Lowest cloud cover wins;
  ``--scene-id`` / ``--mgrs-tile`` pin the choice instead.
- Streams the B02/B03/B04 (blue/green/red) COGs named in the STAC item
  (windowed HTTP reads, nothing under data/ is bulk-downloaded), clips
  to the demo-zone bbox, percentile-stretches each band to uint8, and
  writes chips plus a manifest. Chips that do not intersect the demo
  zone polygon are skipped. An optional 4th band (B08 NIR) is written
  only with ``--nir``; SAM consumes the RGB bands.
- Output: data/imagery/tiles/<scene_id>/manifest.json + chips/*.tif .
  The manifest records scene id, MGRS tile, datetime, cloud cover and,
  per chip, the affine transform + CRS, so pipelines/sam_segment.py can
  polygonize masks back into map coordinates. Rerunning overwrites the
  same deterministic layout.

Requires rasterio/numpy/shapely/pyproj (the SAM env, .venv-sam; see
pipelines/sam_segment.py docstring). Importing this module does not:
heavy deps load inside functions so unit tests run in the base env.
At 10 m/px these chips can evidence disturbed-earth patches, NOT
individual bomb craters (~1 px); see docs/architecture.md hard rules.
"""

import argparse
import gzip
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `python pipelines/tiling.py`

from backend.app.profiles import load_country  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
STAC = "https://earth-search.aws.element84.com/v1"
GADM1_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_{iso}_1.json"
BAND_ASSETS = ("blue", "green", "red")  # B02, B03, B04 (10 m)


def chip_windows(width: int, height: int, chip: int = 1024, overlap: int = 256):
    """(row_off, col_off, h, w) windows covering width x height, edges clipped."""
    if not 0 <= overlap < chip:
        raise ValueError("overlap must be in [0, chip_size)")
    stride = chip - overlap

    def starts(n: int):
        out, s = [], 0
        while s < n:
            out.append(s)
            s += stride
        return out

    return [(r, c, min(chip, height - r), min(chip, width - c))
            for r in starts(height) for c in starts(width)]


def _post_search(body: dict) -> dict:
    req = urllib.request.Request(
        f"{STAC}/search", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def zone_geometry(profile: dict) -> dict:
    """GADM admin-1 geometry for profile['demo_zone_id'] (downloads if absent)."""
    iso = profile["boundaries"]["country_code"]
    dest = REPO_ROOT / "data" / "gadm" / f"gadm41_{iso}_1.json"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading GADM admin-1 data/gadm/{dest.name} ...", flush=True)
        with urllib.request.urlopen(GADM1_URL.format(iso=iso), timeout=180) as resp:
            dest.write_bytes(resp.read())
    doc = json.loads(dest.read_text(encoding="utf-8"))
    for f in doc["features"]:
        if f["properties"].get("GID_1") == profile["demo_zone_id"]:
            return f["geometry"]
    raise ValueError(f"{profile['demo_zone_id']} not found in {dest.name}")


def select_scene(profile: dict, *, scene_id: str | None, mgrs_tile: str | None,
                 start: str, end: str, max_cloud: float) -> dict:
    """One L2A STAC item: pinned by --scene-id, else lowest cloud in range."""
    if scene_id:
        req = urllib.request.Request(f"{STAC}/collections/sentinel-2-l2a/items/{scene_id}")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    body = {
        "collections": ["sentinel-2-l2a"],
        "intersects": zone_geometry(profile),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": max_cloud}},
        "limit": 250,
    }
    items = _post_search(body)["features"]
    if mgrs_tile:
        items = [f for f in items
                 if f["properties"].get("grid:code") == f"MGRS-{mgrs_tile}"]
    if not items:
        raise SystemExit(
            f"no sentinel-2-l2a scene <{max_cloud}% cloud for "
            f"{profile['demo_zone_id']} in {start}..{end}"
            + (f" on tile {mgrs_tile}" if mgrs_tile else ""))
    # Lowest cloud, then most recent.
    items.sort(key=lambda f: (f["properties"]["eo:cloud_cover"],
                              [-ord(ch) for ch in f["properties"]["datetime"]]))
    return items[0]


def _stretch(band, lo: float, hi: float):
    import numpy as np

    out = (band.astype("float32") - lo) * (255.0 / max(hi - lo, 1.0))
    return np.clip(out, 0, 255).astype("uint8")


def tile_scene(item: dict, profile: dict, out_dir: Path,
               chip_size: int, overlap: int, include_nir: bool) -> Path:
    try:
        import rasterio
        from rasterio.windows import from_bounds as window_from_bounds
        from rasterio.warp import transform_bounds, transform_geom
    except ImportError as e:
        raise SystemExit(
            f"tiling needs the SAM env (rasterio): {e}. "
            "Run with .venv-sam\\Scripts\\python.exe (see sam_segment.py).")
    from shapely.geometry import box, shape

    assets = list(BAND_ASSETS) + (["nir"] if include_nir else [])
    hrefs = {a: item["assets"][a]["href"] for a in assets}
    zone = zone_geometry(profile)
    scene_dir = out_dir / item["id"]
    chips_dir = scene_dir / "chips"
    chips_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(hrefs["blue"]) as ref:
        crs = ref.crs
        zb = transform_bounds("EPSG:4326", crs,
                              * _geom_bbox(zone))
        win = window_from_bounds(*zb, transform=ref.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, ref.width, ref.height))
        full_transform = ref.transform
    zone_proj = shape(transform_geom("EPSG:4326", crs, zone))

    arrays, transform = [], None
    for a in assets:
        with rasterio.open(hrefs[a]) as src:
            arr = src.read(1, window=win)
            transform = src.window_transform(win)
        import numpy as np

        valid = arr[arr > 0]
        lo, hi = (np.percentile(valid, [2, 98]) if valid.size else (0, 1))
        arrays.append(_stretch(arr, float(lo), float(hi)))
    import numpy as np

    stack = np.stack(arrays)  # bands, rows, cols
    chips = []
    for row, col, h, w in chip_windows(stack.shape[2], stack.shape[1], chip_size, overlap):
        chip_transform = rasterio.transform.Affine(
            transform.a, transform.b, transform.c + col * transform.a,
            transform.d, transform.e, transform.f + row * transform.e)
        chip_box = box(*rasterio.transform.array_bounds(h, w, chip_transform))
        if not chip_box.intersects(zone_proj):
            continue
        chip_id = f"r{int(win.row_off) + row:05d}_c{int(win.col_off) + col:05d}"
        path = chips_dir / f"{chip_id}.tif"
        with rasterio.open(path, "w", driver="GTiff", height=h, width=w,
                           count=stack.shape[0], dtype="uint8", crs=crs,
                           transform=chip_transform, compress="deflate") as dst:
            dst.write(stack[:, row:row + h, col:col + w])
        t = chip_transform
        chips.append({
            "chip_id": chip_id, "file": f"chips/{path.name}",
            "row_off": int(win.row_off) + row, "col_off": int(win.col_off) + col,
            "height": h, "width": w,
            "transform": {"a": t.a, "b": t.b, "c": t.c, "d": t.d, "e": t.e, "f": t.f},
            "crs": str(crs),
            "bounds": list(rasterio.transform.array_bounds(h, w, t)),
        })
    manifest = {
        "scene_id": item["id"], "collection": "sentinel-2-l2a",
        "mgrs_tile": item["properties"].get("grid:code", "").removeprefix("MGRS-"),
        "datetime": item["properties"].get("datetime"),
        "cloud_cover": item["properties"].get("eo:cloud_cover"),
        "platform": item["properties"].get("platform"),
        "country": profile["id"], "demo_zone_id": profile["demo_zone_id"],
        "bands": {"blue": "B02", "green": "B03", "red": "B04",
                  **({"nir": "B08"} if include_nir else {})},
        "asset_hrefs": hrefs, "chip_size": chip_size, "overlap": overlap,
        "chips": chips,
    }
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"scene {item['id']} tile {manifest['mgrs_tile']} "
          f"cloud {manifest['cloud_cover']}% -> {len(chips)} chips in {scene_dir}")
    return scene_dir / "manifest.json"


def _geom_bbox(geom: dict) -> tuple[float, float, float, float]:
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for x in c:
                walk(x)

    walk(geom["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--country", required=True, help="country profile id, e.g. laos")
    ap.add_argument("--scene-id", help="pin a sentinel-2-l2a item id (skips search)")
    ap.add_argument("--mgrs-tile", help="e.g. 48QUG (default: any tile over the demo zone)")
    ap.add_argument("--start", default="2025-11-01", help="YYYY-MM-DD (dry-season pilot default)")
    ap.add_argument("--end", default="2026-04-30", help="YYYY-MM-DD")
    ap.add_argument("--max-cloud", type=float, default=20.0)
    ap.add_argument("--chip-size", type=int, default=1024)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--nir", action="store_true", help="also write B08 as 4th band")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "imagery" / "tiles")
    args = ap.parse_args(argv)

    profile = load_country(args.country)
    item = select_scene(profile, scene_id=args.scene_id, mgrs_tile=args.mgrs_tile,
                        start=args.start, end=args.end, max_cloud=args.max_cloud)
    print(f"selected {item['id']} ({item['properties'].get('datetime', '')[:10]}, "
          f"cloud {item['properties'].get('eo:cloud_cover')}%, "
          f"{item['properties'].get('grid:code')})")
    tile_scene(item, profile, args.out, args.chip_size, args.overlap, args.nir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
