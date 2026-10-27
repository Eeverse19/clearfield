"""Reproduce data/ from public sources, MD5-checked against docs/data-manifest.md.

Usage: python scripts/download_data.py [file.zip ...]  (no args = all pinned)

Barthelme KH-9 pack (Zenodo 10629987) and OSM (Geofabrik) URLs are pinned;
downloads resume and a checksum failure stops the script. UXOTi_NPA and AMLID
are not pinned yet, and THOR always stays manual (free data.world account):
data.world/datamil/vietnam-war-thor-data -> data/thor/thor_data_vietnam.csv.
Stdlib only, so the .sh/.ps1 wrappers need nothing but Python.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = "https://zenodo.org/api/records/10629987/files"
# (path under data/, url, expected md5, bytes) — MD5s verified in the manifest.
FILES = [
    ("barthelme/README.txt", f"{BASE}/README.txt/content", "44faf252bc8daa32d55d80c4ed668ba7", 3_987),
    ("barthelme/tables.zip", f"{BASE}/tables.zip/content", "fd4f9e034fe4531554a21f89c39f3cb0", 2_516),
    ("barthelme/predictions.zip", f"{BASE}/predictions.zip/content", "c79cd869f7d5bb7bfc0e976c0ff7c783", 47_886_932),
    ("barthelme/data.zip", f"{BASE}/data.zip/content", "ee8860cacf709c5d1d91d0c5ff88b2bd", 1_853_764_395),
    ("barthelme/models.zip", f"{BASE}/models.zip/content", "5afc0bacbd753099e12b48a38f6c3652", 972_209_531),
    # GADM 4.1 admin-1 boundaries. GADM publishes no checksum (md5=None):
    # the script reports the locally computed MD5 instead of verifying one.
    ("gadm/gadm41_LAO_1.json", "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_LAO_1.json", None, 183_636),
    ("gadm/gadm41_KHM_1.json", "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_KHM_1.json", None, 263_580),
    ("gadm/gadm41_VNM_1.json", "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_VNM_1.json", None, 821_030),
    # OSM country extracts (Geofabrik, 2026-10-25 snapshot; ODbL 1.0).
    # MD5s verified against Geofabrik's published .md5 (Oct 27, 2026). The
    # .osm.pbf URLs are the siblings of those .md5 files; dated Geofabrik
    # files may rotate, so a 404 here means re-pin, never skip the MD5.
    ("osm/laos-261025.osm.pbf", "https://download.geofabrik.de/asia/laos-261025.osm.pbf", "bf854b5f14bec74d8854742d227b8695", 53_978_663),
    ("osm/cambodia-261025.osm.pbf", "https://download.geofabrik.de/asia/cambodia-261025.osm.pbf", "7403c81f9de80c012fb930c0758e48ef", 41_150_119),
]


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, total: int) -> None:
    have = dest.stat().st_size if dest.exists() else 0
    req = urllib.request.Request(url)
    if 0 < have < total:
        req.add_header("Range", f"bytes={have}-")
    with urllib.request.urlopen(req) as resp:
        mode = "ab" if (have and resp.status == 206) else "wb"
        if mode == "wb":
            have = 0
        done, step = have, max(total // 10, 1 << 20)
        next_report = done + step
        with dest.open(mode) as f:
            for chunk in iter(lambda: resp.read(1 << 20), b""):
                f.write(chunk)
                done += len(chunk)
                if done >= next_report:
                    print(f"  {done / total:.0%} ({done}/{total} B)", flush=True)
                    next_report += step


def main(argv: list[str]) -> int:
    files = [f for f in FILES if not argv or Path(f[0]).name in argv]
    if not files:
        print(f"no pinned file matches: {argv}", file=sys.stderr)
        return 1
    for rel, url, md5, size in files:
        dest = REPO_ROOT / "data" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and (md5 is None or md5_of(dest) == md5):
            note = "no source checksum" if md5 is None else "md5 verified"
            print(f"OK (present, {note}) data/{rel}")
            continue
        print(f"Downloading data/{rel} ({size} B)...", flush=True)
        download(url, dest, size)
        actual = md5_of(dest)
        if md5 is None:
            print(f"OK (downloaded, no source checksum; local md5 {actual}) data/{rel}")
            continue
        if actual != md5:
            print(f"MD5 MISMATCH: data/{rel} ({actual} != {md5}); "
                  "re-run to resume, do not skip this check", file=sys.stderr)
            return 1
        print(f"OK (downloaded, md5 verified) data/{rel}")
    print("MANUAL (not fetched): data/thor/thor_data_vietnam.csv (data.world account required)")
    print("TODO (URLs not pinned): UXOTi_NPA (Figshare 21688673), AMLID (Zenodo 18001447)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
