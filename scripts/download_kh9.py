"""Georeferenced KH-9 imagery (Edinburgh DataShare) -> data/kh9/.

Usage: python scripts/download_kh9.py [--1mpp]

Downloads the 8 m/px (8mpp) frames for both Barthelme study areas
(Quang Tri ds/7682, tri-border ds/7683) plus their READMEs: ~3.3 GB,
enough for coverage/geolocation QA against the seeded crater
predictions (data/barthelme). The 1 m/px frames (7-16 GB each,
~120 GB total) are NOT bulk-downloaded: crater work reads windows
from the DataShare bitstreams with rasterio when validation needs
them. --1mpp is accepted but currently refuses for that reason;
add frames explicitly here if a full local copy is ever justified.

DataShare publishes no checksums, so local MD5s are computed and
recorded in data/kh9/summary.json (same convention as GADM in
scripts/download_data.py). Downloads are length-verified and
auto-resume on truncated streams / network errors (the Zenodo
lesson from scripts/download_worldstrat.py). Stdlib only.
"""

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = "https://datashare.ed.ac.uk/bitstreams"
OUT = REPO_ROOT / "data" / "kh9"
# (area dir, doi, [(filename, bitstream uuid)])
AREAS = [
    ("quang_tri", "10.7488/ds/7682", [
        ("README.txt", "6bb898cf-5677-42fc-b170-a8e006de3c6a"),
        ("D3C1205-100113A009-8mpp.tif", "31a48e06-d421-4d6d-97f5-a3976627fbff"),
        ("D3C1205-100113A010-8mpp.tif", "97b2b867-59e6-4d9a-9e2f-ce4a4586f82a"),
        ("D3C1205-100113A011-8mpp.tif", "7d04899c-3258-4c10-9c63-d386f309b736"),
        ("D3C1205-100113A012-8mpp.tif", "49c678cd-4924-4899-ab58-41d6a490698b"),
    ]),
    ("tri_border", "10.7488/ds/7683", [
        ("README.txt", "3e4030c6-279d-41b0-a705-527c734f7cb4"),
        ("D3C1204-200292A077-8mpp.tif", "689d38a9-c98a-4d34-ae89-617ab23ed171"),
        ("D3C1204-200292A078-8mpp.tif", "0a0d4d73-0cef-4c27-8567-a66c030aea63"),
        ("D3C1204-200292A079-8mpp.tif", "05248cc8-9728-459f-b013-fcdfd36a0dd9"),
        ("D3C1204-200292A080-8mpp.tif", "c0e73eb2-2c05-42c9-9bf1-1e640def2158"),
        ("D3C1204-200292A081-8mpp.tif", "00b13238-b243-45dc-9e31-6319e900592e"),
        ("D3C1204-200292A082-8mpp.tif", "8cece4d1-1849-46dd-9240-8e2d8420b3d7"),
    ]),
]


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def remote_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return int(resp.headers["Content-Length"])


def download(url: str, dest: Path, total: int) -> None:
    """Resume until complete. `total` (from HEAD) is advisory: DataShare's
    HEAD and GET disagree on some files (observed on the 693 B README,
    where resume then got HTTP 416), so completeness is judged against
    each GET response's own Content-Length, and a 416 restarts clean."""
    import http.client
    import time
    import urllib.error

    for attempt in range(1, 21):
        have = dest.stat().st_size if dest.exists() else 0
        if have == total and have > 0:
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
                expected = have + int(resp.headers["Content-Length"]) \
                    if resp.headers.get("Content-Length") else total
                done = have
                with dest.open(mode) as f:
                    for chunk in iter(lambda: resp.read(1 << 20), b""):
                        f.write(chunk)
                        done += len(chunk)
                if done == expected:
                    return
                total = expected
                print(f"  {dest.name}: stream ended at {done}/{expected}; resuming",
                      flush=True)
        except urllib.error.HTTPError as e:
            if e.code == 416 and dest.exists():
                dest.unlink()
                print(f"  {dest.name}: HTTP 416 (stale partial); restarting clean",
                      flush=True)
                time.sleep(2)
                continue
            print(f"  {dest.name}: network error (HTTPError: {e}); resuming", flush=True)
            time.sleep(10)
        except (urllib.error.URLError, http.client.HTTPException,
                ConnectionError, TimeoutError, OSError) as e:
            print(f"  {dest.name}: network error ({type(e).__name__}: {e}); resuming",
                  flush=True)
            time.sleep(10)
    raise SystemExit(f"download incomplete after 20 attempts: {dest}")


def main(argv: list[str]) -> int:
    if "--1mpp" in argv:
        print("1mpp frames are read as windows from DataShare, not bulk-downloaded "
              "(~120 GB). Remove this guard in scripts/download_kh9.py only with a "
              "specific need.", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"source": "Edinburgh DataShare (Barthelme et al. 2024 imagery)",
               "resolution": "8 m/px frames; 1 m/px deferred to windowed reads",
               "areas": {}}
    for area, doi, files in AREAS:
        dest_dir = OUT / area
        dest_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for name, uuid in files:
            url = f"{BASE}/{uuid}/download"
            dest = dest_dir / name
            total = remote_size(url)
            if dest.exists() and dest.stat().st_size == total:
                print(f"OK (present) data/kh9/{area}/{name}")
            else:
                print(f"Downloading data/kh9/{area}/{name} ({total / 1e6:.0f} MB) ...",
                      flush=True)
                download(url, dest, total)
                print(f"OK data/kh9/{area}/{name}")
            records.append({"file": name, "bytes": dest.stat().st_size,
                            "md5_local": md5_of(dest), "url": url})
        summary["areas"][area] = {"doi": doi, "files": records}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"done -> {OUT} (summary.json; MD5s are locally computed, DataShare "
          "publishes none)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
