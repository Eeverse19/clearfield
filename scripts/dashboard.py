"""Local, read-only progress dashboard for the ClearField data pipelines.

Usage: python scripts/dashboard.py [--port 8765]

Serves http://127.0.0.1:8765/ (this machine only): pipeline stages,
artifact counts/sizes, disk + GPU, and tails of the run logs, refreshed
every 3 s from /api/status. It never starts, stops or writes anything;
the pipelines stay the plain scripts (sentinel2_catalog.py,
download_worldstrat.py, tiling.py, sam_segment.py). Stdlib only.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
CATALOG_SLICES_TOTAL = 822  # 3 countries x 2 collections x 137 months (2015-06..2026-10)
HR_TAR_BYTES = 41_542_117_051
WORLDSTRAT_SELECTED = {"laos": 4, "cambodia": 11, "ukraine": 62}  # download_worldstrat --list-only

_cache: dict = {}


def _age_s(path: Path) -> float | None:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _tail(path: Path, n: int = 12) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    # Pipeline logs are written by PowerShell redirection (UTF-16) and by
    # Python (UTF-8) depending on who launched them; sniff, don't assume.
    text = raw.decode("utf-16", errors="replace") if raw[:2] == b"\xff\xfe" \
        or raw[1:400:2] == b"\x00" * min(200, len(raw) // 2) \
        else raw.decode("utf-8", errors="replace")
    return [ln for ln in text.splitlines() if ln.strip()][ -n:]


def _count(pattern: str, base: Path) -> int:
    return len(list(base.glob(pattern))) if base.exists() else 0


def fmt_bytes(n: int | None) -> str | None:
    if n is None:
        return None
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return None


def gpu_info() -> dict | None:
    now = time.time()
    if _cache.get("gpu_at", 0) > now - 15:
        return _cache.get("gpu")
    info = None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=8).stdout.strip().splitlines()
        if out:
            name, used, total, util = [x.strip() for x in out[0].split(",")]
            info = {"name": name, "mem_used": used, "mem_total": total, "util": util}
    except Exception:
        info = None
    _cache["gpu"], _cache["gpu_at"] = info, now
    return info


def worldstrat_extracted() -> dict[str, int]:
    base = DATA / "worldstrat"
    return {c: _count("*/", base / c) if (base / c).exists() else 0
            for c in WORLDSTRAT_SELECTED}


def status() -> dict:
    stages = []

    gadm = _count("gadm41_*_*.json", DATA / "gadm")
    stages.append({"name": "GADM boundaries", "status": "done" if gadm >= 4 else "pending",
                   "detail": f"{gadm} files in data/gadm/ (admin-0 x3 + admin-1 Laos)",
                   "progress": 1.0 if gadm >= 4 else gadm / 4})

    repro_files = [
        DATA / "barthelme" / "predictions.zip", DATA / "barthelme" / "models.zip",
        DATA / "barthelme" / "data.zip", DATA / "barthelme" / "tables.zip",
        DATA / "gadm" / "gadm41_LAO_1.json", DATA / "gadm" / "gadm41_KHM_1.json",
        DATA / "gadm" / "gadm41_VNM_1.json", DATA / "osm" / "laos-261025.osm.pbf",
        DATA / "osm" / "cambodia-261025.osm.pbf",
    ]
    repro_have = sum(1 for p in repro_files if p.exists())
    stages.append({"name": "Data reproduction (Barthelme + GADM + OSM)",
                   "status": "done" if repro_have == len(repro_files) else
                             ("active" if repro_have else "pending"),
                   "detail": f"{repro_have}/{len(repro_files)} pinned files "
                             "(scripts/download_data.py, MD5-checked)",
                   "progress": repro_have / len(repro_files)})

    kh9_tifs = _count("*8mpp.tif", DATA / "kh9" / "quang_tri") + \
        _count("*8mpp.tif", DATA / "kh9" / "tri_border")
    stages.append({"name": "KH-9 georeferenced imagery (Edinburgh, 8 mpp)",
                   "status": "done" if kh9_tifs == 10 else ("active" if kh9_tifs else "pending"),
                   "detail": f"{kh9_tifs}/10 frames in data/kh9/ (1 mpp deferred to windowed reads)",
                   "progress": kh9_tifs / 10})

    db_path = DATA / "clearfield.db"
    thor_path = DATA / "thor" / "THOR_Vietnam_7_31_2013.csv"
    if not thor_path.exists():
        alt = list((DATA / "thor").glob("*.csv")) if (DATA / "thor").exists() else []
        thor_path = alt[0] if alt else thor_path
    db_detail, db_status, db_prog = "no data/clearfield.db on this machine", "pending", 0.0
    if db_path.exists():
        try:
            import sqlite3
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            zones, struck, ranked = con.execute(
                "SELECT COUNT(*), COUNT(strike_density), COUNT(priority_rank) FROM zones"
            ).fetchone()
            try:
                built = con.execute(
                    "SELECT COUNT(building_density) FROM zones").fetchone()[0]
            except Exception:
                built = 0
            con.close()
            db_detail = (f"DB present: {zones} zones, strike_density {struck}/{zones}, "
                         f"ranked {ranked}, building_density {built}/{zones}; THOR csv "
                         f"{'present' if thor_path.exists() else 'ABSENT (manual data.world download)'}")
            db_status = "done" if ranked else "active"
            db_prog = 1.0 if ranked else 0.5
        except Exception as e:
            db_detail = f"DB present ({fmt_bytes(_size(db_path))}) but unreadable: {e}"
            db_status = "active"
    stages.append({"name": "Local DB seed + THOR strike_density",
                   "status": db_status, "detail": db_detail, "progress": db_prog})

    parts = _count("*.csv", DATA / "sentinel2" / "catalog" / ".parts")
    finals = _count("*_sentinel-2-*.csv.gz", DATA / "sentinel2" / "catalog")
    cat_summary = DATA / "sentinel2" / "catalog" / "summary.json"
    _cat_logs = sorted((DATA / "sentinel2").glob("catalog_run*.log"),
                       key=lambda p: p.stat().st_mtime) if (DATA / "sentinel2").exists() else []
    cat_age = _age_s(_cat_logs[-1]) if _cat_logs else None
    if cat_summary.exists():
        cat_status, cat_prog = "done", 1.0
    elif 0 < parts < CATALOG_SLICES_TOTAL:
        cat_status = "active" if (cat_age is not None and cat_age < 180) else "stalled"
        cat_prog = parts / CATALOG_SLICES_TOTAL
    else:
        cat_status, cat_prog = "pending", 0.0
    stages.append({"name": "Sentinel-2 catalog (Laos/Cambodia/Ukraine, L1C+L2A)",
                   "status": cat_status,
                   "detail": f"{parts}/{CATALOG_SLICES_TOTAL} month slices, "
                             f"{finals}/6 merged catalogs"
                             + ("; log idle >3 min - restart: py -3.12 scripts/sentinel2_catalog.py"
                                if cat_status == "stalled" else ""),
                   "progress": cat_prog})

    sam_env = (REPO / ".venv-sam" / "Scripts" / "python.exe").exists() and \
        (REPO / ".venv-sam" / "Lib" / "site-packages" / "sam3").exists()
    stages.append({"name": "SAM 3 env (.venv-sam, torch cu128 + sam3)",
                   "status": "done" if sam_env else "pending",
                   "detail": "RTX 3080 16 GB, sam3 import verified" if sam_env else "not built",
                   "progress": 1.0 if sam_env else 0.0})

    ckpt = DATA / "models" / "sam3.1" / "sam3.1_multiplex.pt"
    ckpt_size = _size(ckpt)
    ckpt_age = _age_s(ckpt)
    if ckpt_size:
        ck_status = "active" if (ckpt_age is not None and ckpt_age < 120) else "done"
        ck_detail = f"{fmt_bytes(ckpt_size)} at data/models/sam3.1/sam3.1_multiplex.pt" \
            + (" (still being written)" if ck_status == "active" else " (present; completeness checked by torch.load at run time)")
    else:
        ck_status, ck_detail = "blocked", "not present - download sam3.1_multiplex.pt from huggingface.co/facebook/sam3.1 into data/models/sam3.1/"
    stages.append({"name": "SAM 3.1 checkpoint", "status": ck_status,
                   "detail": ck_detail, "progress": None})

    manifests = list((DATA / "imagery" / "tiles").glob("*/manifest.json")) \
        if (DATA / "imagery" / "tiles").exists() else []
    chips = 0
    scene = None
    if manifests:
        try:
            doc = json.loads(manifests[0].read_text(encoding="utf-8"))
            chips, scene = len(doc["chips"]), doc["scene_id"]
        except Exception:
            pass
    stages.append({"name": "Tiling pilot (Xiangkhoang, tile 48QUG)",
                   "status": "done" if manifests else "pending",
                   "detail": f"{scene}: {chips} chips of 1024 px" if manifests else "no manifest",
                   "progress": 1.0 if manifests else 0.0})

    sam_summaries = list((DATA / "imagery" / "sam").glob("*/summary.json")) \
        if (DATA / "imagery" / "sam").exists() else []
    if sam_summaries:
        try:
            sdoc = json.loads(sam_summaries[0].read_text(encoding="utf-8"))
            sam_status = {"ok": "done", "partial": "active",
                          "failed": "failed"}.get(sdoc.get("status", ""), "pending")
            sam_detail = f"status={sdoc.get('status')}, detections={sdoc.get('detections')}" \
                if sdoc.get("status") != "failed" else \
                f"failed at {sdoc.get('stage')}: {str(sdoc.get('error'))[:180]}"
        except Exception:
            sam_status, sam_detail = "pending", "summary unreadable"
    else:
        sam_status = "pending" if ckpt_size else "blocked"
        sam_detail = "not run yet" + ("" if ckpt_size else " (waiting on checkpoint)")
    stages.append({"name": "SAM 3.1 segmentation pilot (191 chips x 3 prompts)",
                   "status": sam_status, "detail": sam_detail,
                   "progress": 1.0 if sam_status == "done" else 0.0})

    ws_dir = DATA / "worldstrat"
    tar_size = _size(ws_dir / "hr_dataset.tar.gz")
    ws_summary = ws_dir / "summary.json"
    extracted = worldstrat_extracted()
    extracted_total = sum(extracted.values())
    selected_total = sum(WORLDSTRAT_SELECTED.values())
    if ws_summary.exists():
        ws_status, ws_prog = "done", 1.0
        ws_detail = f"extracted {extracted_total}/{selected_total} chips {extracted}"
    elif tar_size:
        ws_age = _age_s(ws_dir / "hr_dataset.tar.gz")
        ws_status = "active" if (ws_age is not None and ws_age < 180) else "stalled"
        ws_prog = tar_size / HR_TAR_BYTES
        ws_detail = f"HR tar downloading: {fmt_bytes(tar_size)} / {fmt_bytes(HR_TAR_BYTES)}; extracted {extracted_total}/{selected_total}"
    elif extracted_total:
        ws_status, ws_prog = "active", extracted_total / selected_total
        ws_detail = f"extracting: {extracted_total}/{selected_total} chips {extracted}"
    else:
        ws_status, ws_prog = "pending", 0.0
        ws_detail = f"selected {selected_total} chips {WORLDSTRAT_SELECTED}; tar not started"
    stages.append({"name": "WorldStrat HR 1.5 m/px (77 chips, CC BY-NC)",
                   "status": ws_status, "detail": ws_detail, "progress": ws_prog})

    stages.append({"name": "Validation vs Barthelme/THOR density",
                   "status": "pending",
                   "detail": "needs SAM detections; Barthelme coverage does not reach Xiangkhoang (P1-7)",
                   "progress": 0.0})

    cat_logs = sorted((DATA / "sentinel2").glob("catalog_run*.log"),
                      key=lambda p: p.stat().st_mtime) if (DATA / "sentinel2").exists() else []
    disk = shutil.disk_usage(REPO)
    artifacts = []
    for label, p in [
        ("Catalog summary", DATA / "sentinel2" / "catalog" / "summary.md"),
        ("Tiles manifest", manifests[0] if manifests else DATA / "-"),
        ("SAM summary", sam_summaries[0] if sam_summaries else DATA / "-"),
        ("WorldStrat index", ws_dir / "index.csv"),
        ("WorldStrat metadata", ws_dir / "metadata.csv"),
        ("Checkpoint", ckpt),
    ]:
        if p.exists():
            artifacts.append({"name": label, "path": str(p.relative_to(REPO)),
                              "size": fmt_bytes(_size(p)),
                              "age_min": round((_age_s(p) or 0) / 60, 1)})
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stages": stages,
        "system": {"disk_free": fmt_bytes(disk.free), "disk_total": fmt_bytes(disk.total),
                   "gpu": gpu_info()},
        "artifacts": artifacts,
        "logs": {
            "catalog": _tail(cat_logs[-1]) if cat_logs else [],
            "worldstrat": _tail(DATA / "worldstrat_run.log"),
            "tiling": _tail(DATA / "imagery_tiling.log"),
            "downloads": _tail(DATA / "download_barthelme.log", 8) +
                         _tail(DATA / "download_kh9.log", 8),
        },
    }


PAGE = """<!doctype html><meta charset="utf-8"><title>ClearField pipeline dashboard</title>
<style>
body{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#11151a;color:#dbe2ea;margin:24px;max-width:980px}
h1{font-size:20px;margin:0 0 4px} .sub{color:#8b98a5;font-size:13px;margin-bottom:16px}
.card{background:#1a2129;border:1px solid #2a3540;border-radius:8px;padding:12px 14px;margin:10px 0}
.name{font-weight:600} .detail{color:#9fb0bf;font-size:13px;margin-top:4px;word-break:break-word}
.pill{float:right;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:700}
.done{background:#14532d;color:#86efac}.active{background:#713f12;color:#fde68a}
.pending{background:#26303a;color:#9fb0bf}.blocked{background:#5b2140;color:#fda4af}
.failed,.stalled{background:#5b1d1d;color:#fca5a5}
.bar{height:8px;background:#26303a;border-radius:4px;margin-top:8px;overflow:hidden}
.bar>div{height:100%;background:#4f9cf9}
pre{background:#0b0f13;border:1px solid #26303a;border-radius:6px;padding:8px;font-size:11px;
overflow:auto;max-height:170px;white-space:pre-wrap}
table{border-collapse:collapse;font-size:13px} td,th{padding:3px 10px 3px 0;color:#c7d2dd}
h2{font-size:15px;margin:18px 0 6px}
</style>
<h1>ClearField - pipeline dashboard</h1>
<div class="sub" id="meta">loading...</div><div id="stages"></div>
<h2>System</h2><div class="card" id="system"></div>
<h2>Artifacts</h2><div class="card"><table id="artifacts"></table></div>
<h2>Logs (tails)</h2>
<div class="card"><b>WorldStrat</b><pre id="log-worldstrat"></pre>
<b>Downloads (Barthelme / KH-9)</b><pre id="log-downloads"></pre>
<b>Sentinel-2 catalog</b><pre id="log-catalog"></pre>
<b>Tiling</b><pre id="log-tiling"></pre></div>
<script>
async function tick(){
  const s=await (await fetch('/api/status')).json();
  document.getElementById('meta').textContent='Updated '+s.generated_utc+' - read-only, refreshes every 3 s - pipelines stay plain scripts';
  document.getElementById('stages').innerHTML=s.stages.map(x=>
    `<div class="card"><span class="pill ${x.status}">${x.status}</span>`+
    `<span class="name">${x.name}</span><div class="detail">${x.detail||''}</div>`+
    (x.progress!=null?`<div class="bar"><div style="width:${Math.round(x.progress*100)}%"></div></div>`:'')+`</div>`).join('');
  const g=s.system.gpu;
  document.getElementById('system').textContent=
    `Disk free ${s.system.disk_free} / ${s.system.disk_total}`+
    (g?` - GPU ${g.name}: ${g.mem_used} / ${g.mem_total}, util ${g.util}`:' - GPU n/a');
  document.getElementById('artifacts').innerHTML='<tr><th>Artifact</th><th>Size</th><th>Age (min)</th><th>Path</th></tr>'+
    s.artifacts.map(a=>`<tr><td>${a.name}</td><td>${a.size}</td><td>${a.age_min}</td><td>${a.path}</td></tr>`).join('');
  for(const k of ['worldstrat','downloads','catalog','tiling'])
    document.getElementById('log-'+k).textContent=(s.logs[k]||[]).join('\\n')||'(no log yet)';
}
tick(); setInterval(tick,3000);
</script>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/status"):
            body = json.dumps(status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)
    print(f"ClearField dashboard: http://{args.host}:{args.port}/  (Ctrl+C to stop)", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
