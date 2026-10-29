"""OpenAerialMap drone pockets for Laos / Cambodia / Ukraine.

Usage: python scripts/download_oam.py [--list-only] [--max-mb 250]
           [--countries laos cambodia ukraine]

OpenAerialMap (api.openaerialmap.org) indexes public drone/aerial
mosaics. These are opportunistic uploads, NOT systematic coverage:
small pockets (often <1 km across) at centimetre GSD, useful to
validate detections where a flight happens to exist — never as zone
evidence. The API's bbox counts overstate coverage (border spill from
neighbouring countries), so a pocket counts only when its footprint
centre falls inside the GADM 4.1 admin-0 polygon (cached in
data/gadm/, same representative-point rule as download_worldstrat.py).

Downloads: the GeoTIFF (record `uuid` URL) only when the per-image
license is CC-BY 4.0 and file_size <= --max-mb; everything else is
catalog-only with the reason recorded. Outputs:
  data/oam/index.csv            one row per in-country pocket
  data/oam/catalog.geojson      footprints (all, downloaded or not)
  data/oam/{country}/{_id}.tif  downloaded mosaics
  data/oam/summary.json         counts, sizes, licenses, honesty note
Re-runs resume (existing file with the API's file_size is skipped).
Stdlib only, like the other download scripts.
"""

import csv
import gzip
import hashlib
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API = "https://api.openaerialmap.org/meta"
OUT = REPO_ROOT / "data" / "oam"
COUNTRIES = {"laos": "LAO", "cambodia": "KHM", "ukraine": "UKR"}
# GADM admin-0 bboxes (generous query windows; the polygon decides).
QUERY_BBOX = {
    "laos": (100.0868, 13.9097, 107.635, 22.5004),
    "cambodia": (102.3338, 9.9136, 107.6277, 14.6903),
    "ukraine": (22.1404, 44.386, 40.2181, 52.375),
}
DOWNLOAD_LICENSE = "CC-BY 4.0"


def _load_worldstrat_helpers():
    spec = importlib.util.spec_from_file_location(
        "download_worldstrat", Path(__file__).with_name("download_worldstrat.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_country(bbox) -> list[dict]:
    """All API pages for one bbox (limit=100 per page)."""
    out, page = [], 1
    while True:
        url = (f"{API}?bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
               f"&limit=100&page={page}")
        req = urllib.request.Request(url, headers={"User-Agent": "ClearField"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            doc = json.load(resp)
        out.extend(doc.get("results", []))
        if len(out) >= doc.get("meta", {}).get("found", 0) or not doc.get("results"):
            return out
        page += 1


def record_centre(rec: dict) -> tuple[float, float]:
    b = rec["bbox"]  # [minlon, minlat, maxlon, maxlat]
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def select_in_country(records: list[dict], geoms: dict, ws) -> list[dict]:
    """Keep records whose footprint centre is inside a country polygon."""
    kept = []
    for rec in records:
        lon, lat = record_centre(rec)
        country = next((c for c, g in geoms.items()
                        if ws.point_in_geometry(lon, lat, g)), None)
        if country:
            kept.append({**rec, "_country": country, "_centre": (lon, lat)})
    return kept


def download_decision(rec: dict, max_bytes: int) -> tuple[bool, str]:
    lic = str((rec.get("properties") or {}).get("license", ""))
    if lic != DOWNLOAD_LICENSE:
        return False, f"license {lic or 'unspecified'} != {DOWNLOAD_LICENSE}"
    size = int(rec.get("file_size") or 0)
    if size > max_bytes:
        return False, f"file_size {size} > cap {max_bytes}"
    return True, "ok"


def _download(url: str, dest: Path, total: int) -> None:
    import http.client
    import time
    import urllib.error

    for attempt in range(1, 11):
        have = dest.stat().st_size if dest.exists() else 0
        if have == total:
            return
        if have > total:
            dest.unlink()
            have = 0
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ClearField"})
            if 0 < have < total:
                req.add_header("Range", f"bytes={have}-")
            with urllib.request.urlopen(req, timeout=600) as resp:
                mode = "ab" if (have and resp.status == 206) else "wb"
                if mode == "wb":
                    have = 0
                with dest.open(mode) as f:
                    for chunk in iter(lambda: resp.read(1 << 20), b""):
                        f.write(chunk)
            if dest.stat().st_size == total:
                return
        except (urllib.error.URLError, http.client.HTTPException,
                ConnectionError, TimeoutError, OSError) as e:
            print(f"  {dest.name}: {type(e).__name__}: {e}; resuming", flush=True)
            time.sleep(5)
    raise SystemExit(f"download incomplete after 10 attempts: {dest}")


def main(argv: list[str]) -> int:
    list_only = "--list-only" in argv
    max_mb = 250.0
    if "--max-mb" in argv:
        max_mb = float(argv[argv.index("--max-mb") + 1])
    countries = list(COUNTRIES)
    if "--countries" in argv:
        i = argv.index("--countries")
        countries = [a for a in argv[i + 1:] if not a.startswith("--")]
    max_bytes = int(max_mb * 1e6)

    ws = _load_worldstrat_helpers()
    geoms = ws.load_geometries()
    OUT.mkdir(parents=True, exist_ok=True)

    kept: list[dict] = []
    for country in countries:
        records = fetch_country(QUERY_BBOX[country])
        sel = [r for r in select_in_country(records, geoms, ws)
               if r["_country"] == country]
        total_mb = sum(int(r.get("file_size") or 0) for r in sel) / 1e6
        print(f"{country}: {len(records)} bbox hits -> {len(sel)} in-polygon, "
              f"{total_mb:.0f} MB total")
        kept.extend(sel)

    rows = []
    downloaded = 0
    for rec in kept:
        country = rec["_country"]
        ok, reason = download_decision(rec, max_bytes)
        dest = OUT / country / f"{rec['_id']}.tif"
        did = False
        if ok and not list_only:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and dest.stat().st_size == int(rec["file_size"]):
                did = True
            else:
                print(f"  downloading {country}/{dest.name} "
                      f"({int(rec['file_size']) / 1e6:.1f} MB)", flush=True)
                _download(rec["uuid"], dest, int(rec["file_size"]))
                did = True
            downloaded += did
        props = rec.get("properties") or {}
        rows.append({
            "id": rec["_id"], "country": country,
            "title": (rec.get("title") or "").replace("\n", " "),
            "provider": rec.get("provider", ""), "platform": rec.get("platform", ""),
            "gsd_m": rec.get("gsd", ""), "file_size": rec.get("file_size", ""),
            "acquisition_start": rec.get("acquisition_start", ""),
            "uploaded_at": rec.get("uploaded_at", ""),
            "license": props.get("license", ""),
            "bbox": ";".join(str(x) for x in rec["bbox"]),
            "centre_lon": round(rec["_centre"][0], 6),
            "centre_lat": round(rec["_centre"][1], 6),
            "tif_url": rec["uuid"], "thumbnail": props.get("thumbnail", ""),
            "tms": props.get("tms", ""),
            "downloaded": did, "download_reason": reason if not ok else "ok",
            "local_file": f"{country}/{dest.name}" if did else "",
        })

    with (OUT / "index.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    features = [{
        "type": "Feature",
        "geometry": rec.get("geojson"),
        "properties": {"id": rec["_id"], "country": rec["_country"],
                       "title": rec.get("title", ""),
                       "gsd_m": rec.get("gsd"), "license": (rec.get("properties") or {}).get("license", ""),
                       "acquisition_start": rec.get("acquisition_start", "")},
    } for rec in kept if rec.get("geojson")]
    (OUT / "catalog.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    summary = {
        "source": "OpenAerialMap api.openaerialmap.org/meta (pockets, CC-BY per image)",
        "selection": "footprint centre inside GADM 4.1 admin-0 polygon",
        "pockets": len(rows),
        "per_country": {c: sum(1 for r in rows if r["country"] == c) for c in countries},
        "downloaded": downloaded,
        "max_mb_cap": max_mb,
        "note": "Opportunistic drone pockets at cm GSD for spot validation only; "
                "not systematic coverage and never zone evidence.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
