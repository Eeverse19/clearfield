"""WorldStrat HR chips (1.5 m/px) for Laos / Cambodia / Ukraine only.

Usage: python scripts/download_worldstrat.py [--list-only] [--keep-tar]

WorldStrat (Zenodo 6810792, NeurIPS 2022) pairs ~3,928 high-resolution
Airbus SPOT chips (1.5 m/px, ~2.5 km2 each, single date 2013-2021) with
Sentinel-2 revisits. It is NOT country coverage: chips were sampled for
land-cover stratification, so only a handful land in ClearField
countries. They are useful as improved-resolution places to exercise
SAM 3.1 (see pipelines/sam_segment.py), never as zone evidence -- most
zones get no chip, and the Ukraine chips predate the 2022 invasion.

Selection: a chip belongs to a country when its centre (metadata.csv
lon/lat) falls inside the GADM 4.1 admin-0 polygon already cached at
data/gadm/gadm41_{LAO,KHM,UKR}_0.json (point-in-polygon, stdlib ray
casting; same representative-point rule as scripts/seed_db.py).

The HR archive is a single 41.5 GB tar.gz with no per-chip files, so
this downloads it once (resumable, MD5-verified against the Zenodo
checksum, like scripts/download_data.py), extracts only the selected
chip folders, writes data/worldstrat/index.csv + summary.json, then
deletes the tar unless --keep-tar. The 16 matched Sentinel-2 revisits
per chip are listed in index.csv (lowres_dates) and can be tiled from
the Earth Search catalog; the 27 GB LR tarballs are not downloaded.
HR imagery license: CC BY-NC 4.0 (Airbus) -- non-commercial use only.
Stdlib only, like download_data.py.
"""

import csv
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = "https://zenodo.org/api/records/6810792/files"
METADATA = ("metadata.csv", "dfeb3348e79b719bf03c230d5d258839", 14_562_136)
HR_TAR = ("hr_dataset.tar.gz", "ca7167334006f3c17f9071f14c435335", 41_542_117_051)
COUNTRIES = {"laos": "LAO", "cambodia": "KHM", "ukraine": "UKR"}
OUT = REPO_ROOT / "data" / "worldstrat"


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, total: int) -> None:
    """Resumable download; a stream that ends early is resumed, not trusted.

    Zenodo dropped the 41.5 GB HR tar at ~43% on 2026-10-28: the read
    loop simply saw EOF and the MD5 check (correctly) rejected the file.
    So length is verified here after every attempt and the Range resume
    repeats until the file is exactly `total` bytes (max 20 attempts).
    """
    import http.client
    import time
    import urllib.error

    for attempt in range(1, 21):
        have = dest.stat().st_size if dest.exists() else 0
        if have == total:
            return
        if have > total:
            dest.unlink()
            have = 0
        try:
            req = urllib.request.Request(url)
            if 0 < have < total:
                req.add_header("Range", f"bytes={have}-")
            with urllib.request.urlopen(req) as resp:
                mode = "ab" if (have and resp.status == 206) else "wb"
                if mode == "wb":
                    have = 0
                done, step = have, max(total // 20, 1 << 20)
                next_report = done + step
                with dest.open(mode) as f:
                    for chunk in iter(lambda: resp.read(1 << 20), b""):
                        f.write(chunk)
                        done += len(chunk)
                        if done >= next_report:
                            print(f"  {done / total:.0%} ({done / 1e9:.1f} GB)", flush=True)
                            next_report += step
        except (urllib.error.URLError, http.client.HTTPException,
                ConnectionError, TimeoutError, OSError) as e:
            # e.g. DNS failure mid-resume (observed 2026-10-28 at 63%):
            # whatever bytes landed stay on disk; the loop resumes them.
            print(f"  network error ({type(e).__name__}: {e}); resuming "
                  f"(attempt {attempt}/20)", flush=True)
            time.sleep(10)
            continue
        size = dest.stat().st_size
        if size == total:
            return
        print(f"  stream ended at {size / total:.0%} ({size / 1e9:.1f} GB); "
              f"resuming (attempt {attempt}/20)", flush=True)
        time.sleep(5)
    raise SystemExit(f"download incomplete after 20 attempts: {dest} "
                     f"({dest.stat().st_size}/{total} bytes)")


def point_in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_geometry(x: float, y: float, geom: dict) -> bool:
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:  # poly = [outer, hole, ...]
        if point_in_ring(x, y, poly[0]) and not any(
                point_in_ring(x, y, hole) for hole in poly[1:]):
            return True
    return False


def load_geometries() -> dict[str, dict]:
    geoms = {}
    for country, iso in COUNTRIES.items():
        path = REPO_ROOT / "data" / "gadm" / f"gadm41_{iso}_0.json"
        if not path.exists():
            raise SystemExit(f"missing {path}; run scripts/sentinel2_catalog.py first "
                             "(it caches the GADM admin-0 boundaries)")
        geoms[country] = json.loads(path.read_text(encoding="utf-8"))["features"][0]["geometry"]
    return geoms


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


def select_chips(metadata_csv: Path, geoms: dict[str, dict]) -> list[dict]:
    """One row per HR chip (metadata repeats each chip for 16 LR revisits)."""
    chips: dict[str, dict] = {}
    country_of: dict[str, str | None] = {}  # per chip id, incl. negatives
    bboxes = {c: _geom_bbox(g) for c, g in geoms.items()}
    with metadata_csv.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            chip_id = row[""]
            lon, lat = float(row["lon"]), float(row["lat"])
            if chip_id not in country_of:
                country_of[chip_id] = next(
                    (c for c, g in geoms.items()
                     if bboxes[c][0] <= lon <= bboxes[c][2]
                     and bboxes[c][1] <= lat <= bboxes[c][3]
                     and point_in_geometry(lon, lat, g)), None)
            country = country_of[chip_id]
            if country is None:
                continue
            if chip_id not in chips:
                chips[chip_id] = {
                    "chip_id": chip_id, "country": country,
                    "dir": chip_id.replace(" ", "_"),
                    "lon": lon, "lat": lat, "bounds": row["bounds"],
                    "highres_date": row["highres_date"], "area_km2": row["area"],
                    "lccs_class": row["LCCS class"], "smod_class": row["SMOD Class"],
                    "lowres_dates": set(),
                }
            if chip_id in chips:
                chips[chip_id]["lowres_dates"].add(row["lowres_date"])
    out = sorted(chips.values(), key=lambda c: (c["country"], c["chip_id"]))
    for c in out:
        c["lowres_dates"] = ";".join(sorted(c["lowres_dates"]))
    return out


def extract_selected(tar_path: Path, chips: list[dict]) -> dict[str, int]:
    by_dir = {c["dir"]: c for c in chips}
    found: dict[str, int] = {}
    with tarfile.open(tar_path, "r:gz") as tf:
        for member in tf:
            top = member.name.split("/", 1)[0].replace(" ", "_")
            chip = by_dir.get(top)
            if chip is None or not member.isfile():
                continue
            dest = OUT / chip["country"] / member.name.replace(" ", "_")
            if not dest.resolve().is_relative_to(OUT.resolve()):
                raise SystemExit(f"unsafe tar member: {member.name}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(member) as src, dest.open("wb") as fh:
                for chunk in iter(lambda: src.read(1 << 20), b""):
                    fh.write(chunk)
            found[top] = found.get(top, 0) + 1
    return found


def main(argv: list[str]) -> int:
    list_only = "--list-only" in argv
    keep_tar = "--keep-tar" in argv
    OUT.mkdir(parents=True, exist_ok=True)

    meta_path = OUT / METADATA[0]
    if not (meta_path.exists() and md5_of(meta_path) == METADATA[1]):
        print("Downloading WorldStrat metadata.csv ...", flush=True)
        download(f"{BASE}/metadata.csv/content", meta_path, METADATA[2])
        if md5_of(meta_path) != METADATA[1]:
            print("MD5 MISMATCH on metadata.csv; not proceeding", file=sys.stderr)
            return 1
    chips = select_chips(meta_path, load_geometries())
    per_country = {c: sum(1 for x in chips if x["country"] == c) for c in COUNTRIES}
    print(f"selected chips: {per_country} (total {len(chips)})")
    for c in chips:
        print(f"  {c['country']:9s} {c['chip_id']}  centre {c['lon']:.4f},{c['lat']:.4f}  "
              f"HR {c['highres_date']}")
    if list_only:
        return 0

    summary_path = OUT / "summary.json"
    if summary_path.exists():
        prev = json.loads(summary_path.read_text(encoding="utf-8"))
        if prev.get("chips_extracted") == len(chips) and prev.get("hr_tar_md5_verified"):
            print("OK (already extracted and MD5-verified; use --keep-tar run or "
                  "delete summary.json to redo)")
            return 0

    tar_path = OUT / HR_TAR[0]
    print(f"Downloading {HR_TAR[0]} ({HR_TAR[2] / 1e9:.1f} GB, resumable) ...", flush=True)
    download(f"{BASE}/hr_dataset.tar.gz/content", tar_path, HR_TAR[2])
    actual = md5_of(tar_path)
    if actual != HR_TAR[1]:
        print(f"MD5 MISMATCH: {actual} != {HR_TAR[1]}; tar kept for resume/retry, "
              "nothing extracted", file=sys.stderr)
        return 1
    print("MD5 verified. Extracting selected chips ...", flush=True)
    found = extract_selected(tar_path, chips)
    missing = [c["chip_id"] for c in chips if c["dir"] not in found]
    if missing:
        print(f"WARNING: {len(missing)} selected chips not in tar: {missing}", file=sys.stderr)

    with (OUT / "index.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["chip_id", "country", "dir", "lon", "lat", "bounds", "highres_date",
                    "area_km2", "lccs_class", "smod_class", "lowres_dates", "files_extracted"])
        for c in chips:
            w.writerow([c["chip_id"], c["country"], c["dir"], c["lon"], c["lat"], c["bounds"],
                        c["highres_date"], c["area_km2"], c["lccs_class"], c["smod_class"],
                        c["lowres_dates"], found.get(c["dir"], 0)])
    summary = {
        "source": "https://zenodo.org/records/6810792 (WorldStrat, NeurIPS 2022)",
        "hr_archive": HR_TAR[0], "hr_tar_md5_verified": True,
        "hr_license": "CC BY-NC 4.0 (Airbus SPOT) - non-commercial only",
        "selection": "chip centre inside GADM 4.1 admin-0 polygon (data/gadm/)",
        "chips_selected": len(chips), "chips_extracted": len(found),
        "per_country": per_country, "chips_missing": missing,
        "note": "Single-date HR 2013-2021; Ukraine chips predate 2022. Matched "
                "Sentinel-2 revisits are in index.csv lowres_dates, not downloaded.",
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if keep_tar:
        print(f"tar kept at {tar_path}")
    else:
        tar_path.unlink()
        print("tar deleted (MD5 was verified; re-run reproduces it)")
    print(f"done: {len(found)} chips -> {OUT} (index.csv, summary.json)")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
