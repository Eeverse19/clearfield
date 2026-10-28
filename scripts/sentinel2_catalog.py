"""Catalog (not download) Sentinel-2 scenes for whole countries via STAC.

Usage: python scripts/sentinel2_catalog.py [--countries laos cambodia ukraine]
           [--collections sentinel-2-l1c sentinel-2-l2a] [--workers 4]
           [--start 2015-06] [--end 2026-10] [--merge-only]

Source: Earth Search STAC v1 (https://earth-search.aws.element84.com/v1),
the endpoint linked from https://registry.opendata.aws/sentinel-2/ for the
`sentinel-s2-l1c` / `sentinel-s2-l2a` buckets in eu-central-1. No imagery is
downloaded and no AWS account is needed: each catalog row records the scene
id, datetime, MGRS tile, cloud cover and the B02/B03/B04/B08 (blue/green/
red/NIR, 10 m) asset hrefs only. L2A hrefs are public COG https URLs; L1C
hrefs are s3:// URLs in the Requester-Pays `sentinel-s2-l1c` bucket.

Country geometry is the GADM 4.1 admin-0 polygon (cached under
data/gadm/, same source as the admin-1 files in download_data.py), used as
a STAC `intersects` filter -- never the bounding box, which would pull in
scenes over neighbouring countries. Ukraine is catalogued by geometry
only; it deliberately gets no profile under countries/.

Output (all under data/, gitignored):
  data/sentinel2/catalog/{country}_{collection}.csv.gz   one row per scene
  data/sentinel2/catalog/{country}_mgrs_tiles.geojson    distinct tiles
  data/sentinel2/catalog/summary.json / summary.md       counts + QA
Work is sliced by calendar month into data/sentinel2/catalog/.parts/ so a
re-run resumes where it stopped; delete a .parts file to redo that month.
Page size is 250: Earth Search returns 502 for >=500 with these large
intersects geometries. Stdlib only, like download_data.py.
"""

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STAC_SEARCH = "https://earth-search.aws.element84.com/v1/search"
GADM_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_{iso}_0.json"
COUNTRIES = {"laos": "LAO", "cambodia": "KHM", "ukraine": "UKR"}
COLLECTIONS = ["sentinel-2-l1c", "sentinel-2-l2a"]
# Full archive: L1C starts 2015-06-23; L2A is in the same API from
# 2016-11 (earlier months simply return 0 items, one cheap request each).
ARCHIVE_START = (2015, 6)
PAGE_LIMIT = 250
BAND_ASSETS = [("blue", "b02"), ("green", "b03"), ("red", "b04"), ("nir", "b08")]
CSV_FIELDS = [
    "country", "collection", "id", "datetime", "mgrs_tile", "platform",
    "cloud_cover", "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy",
    "b02_href", "b03_href", "b04_href", "b08_href", "item_href",
]
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def months(start: tuple[int, int], end: tuple[int, int]):
    """Yield ((y, m), 'YYYY-MM-01T00:00:00Z', next-month same) per month."""
    y, m = start
    while (y, m) <= end:
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield (y, m), f"{y:04d}-{m:02d}-01T00:00:00Z", f"{ny:04d}-{nm:02d}-01T00:00:00Z"
        y, m = ny, nm


def parse_month(text: str) -> tuple[int, int]:
    y, m = text.split("-")
    return int(y), int(m)


def feature_row(country: str, collection: str, f: dict) -> list:
    p = f.get("properties", {})
    assets = f.get("assets", {})
    bbox = f.get("bbox") or ["", "", "", ""]
    item_href = next(
        (l.get("href", "") for l in f.get("links", []) if l.get("rel") == "self"), ""
    )
    row = [
        country, collection, f.get("id", ""), p.get("datetime", ""),
        str(p.get("grid:code", "")).removeprefix("MGRS-"),
        p.get("platform", ""), p.get("eo:cloud_cover", ""),
        *[f"{v:.6f}" if isinstance(v, float) else v for v in bbox],
    ]
    row += [assets.get(name, {}).get("href", "") for name, _ in BAND_ASSETS]
    row.append(item_href)
    return row


def post_search(body: dict, retries: int = 7) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        STAC_SEARCH, data=data,
        headers={"Content-Type": "application/json", "Accept-Encoding": "gzip"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            return json.loads(raw)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", None)
            if code is not None and code not in (429, 500, 502, 503, 504):
                raise
            if attempt == retries - 1:
                raise
            time.sleep(min(60, 3 * 2**attempt))
    raise AssertionError("unreachable")


def fetch_month(task: dict) -> tuple[str, int, bool]:
    """Download one month slice to .parts/; returns (key, rows, skipped)."""
    key = f"{task['country']}_{task['collection']}_{task['ym'][0]:04d}-{task['ym'][1]:02d}"
    part_csv = task["parts"] / f"{key}.csv"
    part_tiles = task["parts"] / f"{key}.tiles.json"
    if part_csv.exists():
        with part_csv.open(newline="", encoding="utf-8") as fh:
            return key, sum(1 for _ in fh), True
    body = {
        "collections": [task["collection"]],
        "intersects": task["geometry"],
        "datetime": f"{task['t0']}/{task['t1']}",
        "limit": task.get("page_limit", PAGE_LIMIT),
    }
    tmp_csv = task["parts"] / f"{key}.{threading.get_ident()}.tmp"
    try:
        return _fetch_month_pages(task, key, part_csv, part_tiles, tmp_csv, body)
    except Exception:
        tmp_csv.unlink(missing_ok=True)
        raise


def _fetch_month_pages(task, key, part_csv, part_tiles, tmp_csv, body):
    tiles: dict[str, dict] = {}
    rows = 0
    with tmp_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        while True:
            page = post_search(body)
            for f in page.get("features", []):
                writer.writerow(feature_row(task["country"], task["collection"], f))
                rows += 1
                tile = str(f.get("properties", {}).get("grid:code", "")).removeprefix("MGRS-")
                if tile and tile not in tiles and f.get("geometry"):
                    tiles[tile] = f["geometry"]
            nxt = next((l for l in page.get("links", []) if l.get("rel") == "next"), None)
            if not nxt or not page.get("features"):
                break
            body = nxt["body"]  # merge=false: body is the complete next request
    tmp_csv.replace(part_csv)
    part_tiles.write_text(json.dumps(tiles), encoding="utf-8")
    return key, rows, False


def slice_key(task: dict) -> str:
    return f"{task['country']}_{task['collection']}_{task['ym'][0]:04d}-{task['ym'][1]:02d}"


def run_tasks(tasks: list[dict], workers: int, fetch=fetch_month) -> tuple[int, list[dict]]:
    """Run slices concurrently; a failing slice never kills the run.

    Failures are retried once, sequentially, at page size 100 (Earth
    Search intermittently 502s on 250-item pages with these large
    intersects geometries). Returns (total_rows, still_failed_tasks).
    """
    done = skipped = total_rows = 0
    failed: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, t): t for t in tasks}
        for fut in as_completed(futures):
            task = futures[fut]
            try:
                _key, rows, was_skipped = fut.result()
            except Exception as e:
                log(f"  slice {slice_key(task)} failed ({type(e).__name__}: {e}); "
                    "queued for retry")
                failed.append(task)
                continue
            done += 1
            skipped += was_skipped
            total_rows += rows
            if done % 25 == 0:
                log(f"  {done}/{len(tasks)} slices ({skipped} resumed), {total_rows} rows")
    still_failed: list[dict] = []
    for task in failed:
        log(f"  retrying {slice_key(task)} at page size 100 ...")
        try:
            _key, rows, _skip = fetch({**task, "page_limit": 100})
            total_rows += rows
            done += 1
        except Exception as e:
            log(f"  slice {slice_key(task)} failed again ({type(e).__name__}: {e})")
            still_failed.append(task)
    log(f"  {done}/{len(tasks)} slices ({skipped} resumed), {total_rows} rows, "
        f"{len(still_failed)} failed")
    return total_rows, still_failed


def load_geometry(iso: str) -> dict:
    dest = REPO_ROOT / "data" / "gadm" / f"gadm41_{iso}_0.json"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = GADM_URL.format(iso=iso)
        log(f"Downloading GADM admin-0 boundary data/gadm/{dest.name} ...")
        with urllib.request.urlopen(url, timeout=180) as resp:
            dest.write_bytes(resp.read())
        md5 = hashlib.md5(dest.read_bytes()).hexdigest()
        log(f"  saved (GADM publishes no checksum; local md5 {md5})")
    doc = json.loads(dest.read_text(encoding="utf-8"))
    return doc["features"][0]["geometry"]


def expected_count(collection: str, geometry: dict) -> int | None:
    try:
        page = post_search({"collections": [collection], "intersects": geometry, "limit": 1})
        return page.get("numberMatched")
    except Exception as e:  # informational only; never fail the catalog on it
        log(f"  warning: numberMatched query failed for {collection}: {e}")
        return None


def merge(country: str, collection: str, out: Path, parts: Path) -> dict:
    seen: set[str] = set()
    rows: list[list] = []
    dupes = 0
    tile_geom: dict[str, dict] = {}
    tile_stats: dict[str, dict] = {}
    prefix = f"{country}_{collection}_"
    for part in sorted(parts.glob(f"{prefix}*.csv")):
        tiles_doc = parts / (part.stem + ".tiles.json")
        if tiles_doc.exists():
            for tile, geom in json.loads(tiles_doc.read_text(encoding="utf-8")).items():
                tile_geom.setdefault(tile, geom)
        with part.open(newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if row[2] in seen:
                    dupes += 1
                    continue
                seen.add(row[2])
                rows.append(row)
                st = tile_stats.setdefault(
                    row[4], {"items": 0, "first": row[3], "last": row[3],
                             "cloud_sum": 0.0, "cloud_n": 0})
                st["items"] += 1
                st["first"] = min(st["first"], row[3])
                st["last"] = max(st["last"], row[3])
                try:
                    st["cloud_sum"] += float(row[6])
                    st["cloud_n"] += 1
                except (ValueError, IndexError):
                    pass
    rows.sort(key=lambda r: (r[3], r[4], r[2]))
    dest = out / f"{country}_{collection}.csv.gz"
    with gzip.open(dest, "wt", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_FIELDS)
        writer.writerows(rows)
    clouds = []
    for r in rows:
        try:
            clouds.append(float(r[6]))
        except ValueError:
            pass
    summary = {
        "country": country, "collection": collection,
        "file": dest.name, "bytes": dest.stat().st_size,
        "items": len(rows), "duplicate_ids_dropped": dupes,
        "mgrs_tiles": len(tile_stats),
        "datetime_min": rows[0][3] if rows else None,
        "datetime_max": rows[-1][3] if rows else None,
        "cloud_cover_mean": round(sum(clouds) / len(clouds), 2) if clouds else None,
        "items_cloud_lt_10": sum(1 for c in clouds if c < 10),
        "items_cloud_lt_20": sum(1 for c in clouds if c < 20),
    }
    return {"summary": summary, "tile_geom": tile_geom, "tile_stats": tile_stats}


def write_tiles(country: str, merged: list[dict], out: Path) -> Path:
    geom: dict[str, dict] = {}
    stats: dict[str, dict] = {}
    for m in merged:
        for tile, g in m["tile_geom"].items():
            geom.setdefault(tile, g)
        for tile, st in m["tile_stats"].items():
            agg = stats.setdefault(tile, {"items": 0, "first": st["first"], "last": st["last"],
                                          "by_collection": {}})
            agg["items"] += st["items"]
            agg["first"] = min(agg["first"], st["first"])
            agg["last"] = max(agg["last"], st["last"])
            agg["by_collection"][m["summary"]["collection"]] = {
                "items": st["items"],
                "cloud_cover_mean": round(st["cloud_sum"] / st["cloud_n"], 2)
                if st["cloud_n"] else None,
            }
    features = [{
        "type": "Feature",
        "geometry": geom[tile],
        "properties": {"mgrs_tile": tile, "country": country, **stats[tile]},
    } for tile in sorted(stats)]
    dest = out / f"{country}_mgrs_tiles.geojson"
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": features}),
                    encoding="utf-8")
    return dest


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--countries", nargs="+", default=list(COUNTRIES), choices=list(COUNTRIES))
    ap.add_argument("--collections", nargs="+", default=COLLECTIONS, choices=COLLECTIONS)
    ap.add_argument("--start", type=parse_month, default=ARCHIVE_START, help="YYYY-MM")
    ap.add_argument("--end", type=parse_month, default=None, help="YYYY-MM (default: current UTC month)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "sentinel2" / "catalog")
    ap.add_argument("--merge-only", action="store_true")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    end = args.end or (now.year, now.month)
    out: Path = args.out
    parts = out / ".parts"
    out.mkdir(parents=True, exist_ok=True)
    parts.mkdir(parents=True, exist_ok=True)

    geometries = {c: load_geometry(COUNTRIES[c]) for c in args.countries}
    expected = {}
    for country in args.countries:
        for collection in args.collections:
            expected[f"{country}/{collection}"] = expected_count(collection, geometries[country])
            log(f"Earth Search numberMatched {country}/{collection}: "
                f"{expected[f'{country}/{collection}']}")

    if not args.merge_only:
        tasks = []
        for country in args.countries:
            for collection in args.collections:
                for ym, t0, t1 in months(args.start, end):
                    tasks.append({"country": country, "collection": collection,
                                  "ym": ym, "t0": t0, "t1": t1,
                                  "geometry": geometries[country], "parts": parts})
        log(f"{len(tasks)} month slices, {args.workers} workers, page size {PAGE_LIMIT}")
        _rows, still_failed = run_tasks(tasks, args.workers)
        failed_path = out / "failed_slices.json"
        if still_failed:
            failed_path.write_text(json.dumps(
                [slice_key(t) for t in still_failed], indent=2), encoding="utf-8")
            log(f"ERROR: {len(still_failed)} slices failed after retry; listed in "
                f"{failed_path}. Completed slices are kept in .parts - re-run to "
                "resume. Not merging an incomplete catalog.")
            return 1
        failed_path.unlink(missing_ok=True)

    summaries = []
    for country in args.countries:
        merged = []
        for collection in args.collections:
            m = merge(country, collection, out, parts)
            m["summary"]["api_numberMatched_at_run"] = expected.get(f"{country}/{collection}")
            summaries.append(m["summary"])
            merged.append(m)
            log(f"merged {country}/{collection}: {m['summary']['items']} items, "
                f"{m['summary']['mgrs_tiles']} tiles -> {m['summary']['file']}")
        tiles_path = write_tiles(country, merged, out)
        log(f"tiles -> {tiles_path.name}")

    doc = {
        "generated_utc": now.isoformat(),
        "source": STAC_SEARCH,
        "registry": "https://registry.opendata.aws/sentinel-2/",
        "bands_recorded": {"blue": "B02", "green": "B03", "red": "B04", "nir": "B08"},
        "note": "Catalog only: no imagery downloaded. L1C hrefs are s3:// in the "
                "Requester-Pays sentinel-s2-l1c bucket; L2A hrefs are public COGs. "
                "Counts vs api_numberMatched_at_run can differ by scenes added "
                "while the run was in progress (current month is still filling).",
        "catalogs": summaries,
    }
    (out / "summary.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    lines = ["# Sentinel-2 catalog summary", "",
             f"Generated {doc['generated_utc']} from Earth Search STAC v1. "
             "Catalog only - no imagery downloaded.", "",
             "| Country | Collection | Items | Tiles | Dates | Mean cloud % | <20% cloud | File |",
             "|---|---|---:|---:|---|---:|---:|---|"]
    for s in summaries:
        lines.append(
            f"| {s['country']} | {s['collection']} | {s['items']} | {s['mgrs_tiles']} "
            f"| {str(s['datetime_min'])[:10]}..{str(s['datetime_max'])[:10]} "
            f"| {s['cloud_cover_mean']} | {s['items_cloud_lt_20']} | {s['file']} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"summary -> {out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
