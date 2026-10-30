"""Catalog CBERS-4A WPM scenes (2 m pan, CC BY 4.0) for the 3 countries.

Usage: python scripts/cbers_catalog.py [--countries laos cambodia ukraine]

Source: Brazil Data Cube STAC (data.inpe.br), collection
CB4A-WPM-L2-DN-1 — CBERS-4A Wide-Field Panchromatic/Multispectral
camera: BAND0 is 2 m panchromatic, BAND1-4 are 8 m multispectral.
License CC BY 4.0 (collection `license` field) — the only free,
commercially usable ~2 m source found in the 2026-10-28 imagery
review (docs/bomb-finding-research.md context). Coverage is sparse
(downlink-driven, not wall-to-wall) and products are L2
(system-corrected, NOT orthorectified): scenes need RPC orthorectification
before pixel work. This script catalogs only — no imagery is downloaded.

Selection: STAC `intersects` with the GADM 4.1 admin-0 polygon (cached
in data/gadm/), never just the bbox. Output:
  data/cbers/{country}_cbers4a_wpm.csv  (id, datetime, bbox, band hrefs)
  data/cbers/summary.json / summary.md  (counts + demo-zone overlap)
Stdlib only, like scripts/sentinel2_catalog.py.
"""

import argparse
import csv
import gzip
import importlib.util
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STAC_SEARCH = "https://data.inpe.br/bdc/stac/v1/search"
COLLECTION = "CB4A-WPM-L2-DN-1"
COUNTRIES = {"laos": "LAO", "cambodia": "KHM", "ukraine": "UKR"}
DEMO_ZONES = {"laos": "LAO.18_1", "cambodia": "KHM.25_1"}  # ukraine: no profile/zones
OUT = REPO_ROOT / "data" / "cbers"
PAGE_LIMIT = 200


def _load_worldstrat_helpers():
    spec = importlib.util.spec_from_file_location(
        "download_worldstrat",
        Path(__file__).with_name("download_worldstrat.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def post_search(body: dict) -> dict:
    req = urllib.request.Request(
        STAC_SEARCH, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def fetch_country(country: str, geometry: dict) -> list[dict]:
    """All WPM items intersecting the country polygon (paged)."""
    items, seen, page = [], set(), 1
    while True:
        body = {"collections": [COLLECTION], "intersects": geometry,
                "limit": PAGE_LIMIT, "page": page}
        try:
            doc = post_search(body)
        except urllib.error.HTTPError:
            if page > 1:
                break
            raise
        feats = doc.get("features", [])
        fresh = [f for f in feats if f["id"] not in seen]
        for f in fresh:
            seen.add(f["id"])
        items.extend(fresh)
        if len(feats) < PAGE_LIMIT or not fresh:
            return items
        page += 1


def zone_geometry(iso: str, gid: str) -> dict:
    path = REPO_ROOT / "data" / "gadm" / f"gadm41_{iso}_1.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    for f in doc["features"]:
        if f["properties"].get("GID_1") == gid:
            return f["geometry"]
    raise ValueError(f"{gid} not found in {path.name}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--countries", nargs="+", default=list(COUNTRIES),
                    choices=list(COUNTRIES))
    args = ap.parse_args(argv)

    ws = _load_worldstrat_helpers()
    geoms = ws.load_geometries()
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {
        "source": STAC_SEARCH, "collection": COLLECTION,
        "license": "CC BY 4.0 (collection license field)",
        "note": "Catalog only. BAND0 = 2 m panchromatic, BAND1-4 = 8 m MS; "
                "L2 system-corrected, not orthorectified. Sparse coverage.",
        "countries": {},
    }
    for country in args.countries:
        items = fetch_country(country, geoms[country])
        rows = []
        for f in items:
            assets = f.get("assets", {})
            rows.append({
                "country": country, "id": f["id"],
                "datetime": f.get("properties", {}).get("datetime", ""),
                "bbox": ";".join(str(x) for x in f.get("bbox", [])),
                "band0_2m_pan": assets.get("BAND0", {}).get("href", ""),
                "band2_8m": assets.get("BAND2", {}).get("href", ""),
                "band3_8m": assets.get("BAND3", {}).get("href", ""),
                "band4_8m": assets.get("BAND4", {}).get("href", ""),
                "thumbnail": assets.get("thumbnail", {}).get("href", ""),
            })
        rows.sort(key=lambda r: (r["datetime"], r["id"]))
        dest = OUT / f"{country}_cbers4a_wpm.csv"
        with dest.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                               ["country", "id", "datetime", "bbox", "band0_2m_pan",
                                "band2_8m", "band3_8m", "band4_8m", "thumbnail"])
            w.writeheader()
            w.writerows(rows)
        entry = {"scenes": len(rows), "file": dest.name,
                 "datetime_min": rows[0]["datetime"][:10] if rows else None,
                 "datetime_max": rows[-1]["datetime"][:10] if rows else None}
        gid = DEMO_ZONES.get(country)
        if gid:
            zone = zone_geometry(COUNTRIES[country], gid)
            in_zone = overlap = 0
            zb = ws._geom_bbox(zone)
            for r in rows:
                bb = [float(x) for x in r["bbox"].split(";")]
                cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                if ws.point_in_geometry(cx, cy, zone):
                    in_zone += 1
                if not (bb[2] < zb[0] or bb[0] > zb[2] or bb[3] < zb[1] or bb[1] > zb[3]):
                    overlap += 1
            entry["demo_zone"] = gid
            entry["scenes_centre_in_demo_zone"] = in_zone
            entry["scenes_footprint_bbox_overlaps_demo_zone"] = overlap
        summary["countries"][country] = entry
        print(f"{country}: {entry['scenes']} scenes -> {dest.name} "
              f"({entry['datetime_min']}..{entry['datetime_max']})"
              + (f"; demo zone {gid}: {entry.get('scenes_centre_in_demo_zone')}"
                 if gid else ""))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# CBERS-4A WPM catalog (2 m pan, CC BY 4.0)", "",
             "Catalog only - no imagery downloaded. L2, not orthorectified.", "",
             "| Country | Scenes | Dates | Demo zone scenes | File |",
             "|---|---:|---|---|---|"]
    for country, e in summary["countries"].items():
        dz = e.get('scenes_footprint_bbox_overlaps_demo_zone', '-')
        lines.append(f"| {country} | {e['scenes']} | {e['datetime_min']}..{e['datetime_max']} "
                     f"| {dz} (footprint bbox overlap) | {e['file']} |")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"summary -> {OUT / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
