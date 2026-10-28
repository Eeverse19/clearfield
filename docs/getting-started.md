# Getting started

Target audience: a developer (or a future contributor) setting ClearField up from scratch. Estimated time once the pieces exist: ~30 minutes plus download time.

> Status (Oct 28, 2026): sections 1, 2 (pinned files only), 3 (SQLite seed), 4, and 7 work today; the local DB is seeded (106 zones, 541,397 craters; OSM exposure for Laos + Cambodia). Section 5: `osm_exposure.py` + `scoring.py` work; THOR `strike_density` is seeded on 106/106 zones (corrected seed per `docs/thor/thor_final_spec.md` §9, real run 2026-10-28) and scoring ranks Laos 4/18, Cambodia 2/25, Vietnam 0/63 (Vietnam has no OSM exposure; the other unscored zones lack `crater_evidence`). `tiling.py` is implemented (Sentinel-2 L2A scene → 1024 px chips; Xiangkhoang pilot scene done, 191 chips) and `sam_segment.py` is implemented (SAM 3.1 local, per-chip cache) but has not run: the gated `facebook/sam3.1` checkpoint is not yet in `data/models/sam3.1/`. The Sentinel-2 catalog is complete (630,318 scenes, Laos/Cambodia/Ukraine, L1C+L2A); WorldStrat HR extraction (77 chips) is in progress. Monitor everything at http://127.0.0.1:8765/ (`scripts/dashboard.py`). `META_API_KEY` is still to be provided (Spark only; SAM runs locally without it). Full audit: [`../WORKFLOW_SYNTHESIS.md`](../WORKFLOW_SYNTHESIS.md) (Oct 27, pre-imagery-pipeline).

## Prerequisites

- Python 3.11+ via `uv` (manages the project-local `.venv`; on this Windows machine `uv sync` is the only setup step)
- PostgreSQL 15+ with PostGIS (target DB; the scaffold runs on the SQLite mirror in `db/schema.local.sql` first)
- A Meta Model API key (dev.meta.ai) for Spark — put it in `.env`, never in code. SAM 3.1 does **not** need it: SAM runs locally (below). (The Meta Model API also hosts `sam-3.1`, but that route is not wired.)
- For SAM locally: an NVIDIA GPU (tested: RTX 3080 Laptop 16 GB, CUDA 12.8+ driver), Python 3.12 for the separate `.venv-sam` env, a Hugging Face account approved for the gated `facebook/sam3.1` checkpoint, and ~10 GB for env + checkpoint (~3.4 GB)
- ~1 GB free disk for today's footprint (seeded DB ≈826 MB + predictions.zip 48 MB); THOR adds 457,332,289 B (zip) + 2,627,971,171 B (csv); ~8 GB if Barthelme `data.zip`/`models.zip` are also fetched; the WorldStrat HR tar is a 41.5 GB transient (MD5-verified, extracted, then deleted by `scripts/download_worldstrat.py`)
- Optional: a GPU machine for local Glimmer testing (Modal is not used anywhere)

## 1. Clone and configure

```bash
git clone <repo-url> clearfield && cd clearfield
cp .env.example .env
# Edit .env: META_API_KEY, DATABASE_URL
```

## 2. Get the data (nothing is committed)

```powershell
# Windows wrapper (scripts/download_data.sh on Linux/macOS); no args = all pinned files
scripts\download_data.ps1 predictions.zip tables.zip README.txt gadm41_LAO_1.json gadm41_KHM_1.json gadm41_VNM_1.json
```

Pinned today: the Barthelme KH-9 crater pack (Zenodo 10629987), GADM 4.1 admin-1 boundaries for LAO/KHM/VNM, and Geofabrik OSM extracts for Laos + Cambodia (`-261025`, ODbL 1.0). Barthelme and OSM files are MD5-checked against `docs/data-manifest.md` — a mismatch stops the script; re-run it (downloads resume). GADM publishes no checksum, so the script reports locally computed MD5s. UXOTi_NPA and AMLID are not pinned yet; Barthelme `data.zip`/`models.zip` (≈2.8 GB) download only if you ask for all files.

**Two manual steps the script cannot do for you:**
- **THOR**: free data.world account, download `THOR_Vietnam.zip` (457,332,289 B) from data.world/datamil/vietnam-war-thor-data, extract with 7-Zip (Deflate64 — Explorer/zipfile/tar fail) into `data/thor/` -> `THOR_Vietnam_7_31_2013.csv` (2,627,971,171 B). Then `python scripts/seed_thor.py` writes `zones.strike_density` (corrected seed per `docs/thor/thor_final_spec.md` §9; real run done 2026-10-28 — see `TASKS.md` P0-1).
- **Raw KH-9 scans** (if you want them): free USGS EROS account at earthexplorer.usgs.gov, Declassified Data > Declass 3 collection. The georeferenced Barthelme versions (Edinburgh DataShare ds/7682, ds/7683) cover the demo areas and need no account.

## 3. Database

```powershell
# Today (SQLite mirror; PostGIS schema in db/schema.sql is the target, not yet wired):
scripts\seed_db.ps1   # ~65 min: GADM zones + Barthelme craters -> data/clearfield.db
# seed_db loads GADM + Barthelme only; seed_thor adds THOR strike_density and osm_exposure adds OSM exposure (Laos + Cambodia done, Vietnam not acquired).
# Target: createdb clearfield; psql clearfield -f db/schema.sql; seed incl. THOR/OSM.
```

Schema notes: zones carry their score *components* (strike density, crater evidence, exposure, surveyed status) as columns, not just a final score — the explanation layer cites these, so they must never be dropped in a migration.

## 4. Run

```powershell
# Backend (FastAPI) — canonical env is uv + pyproject.toml
uv sync
uv run uvicorn backend.app.main:app --reload   # http://localhost:8000, docs at /docs
# pip fallback: python -m venv .venv; pip install -r backend/requirements.txt

# Frontend (static, no build step)
start frontend/index.html
# or: uv run python -m http.server 8080 --directory frontend
```

## 5. Run the pipelines (in order)

```powershell
# Imagery chain (Oct 28; all outputs under data/, gitignored; monitor via scripts/dashboard.py)
py -3.12 scripts/sentinel2_catalog.py                # Sentinel-2 catalog (done: 630,318 scenes)
py -3.12 scripts/download_worldstrat.py              # WorldStrat HR 1.5 m/px chips (77, CC BY-NC)
# SAM env (once): py -3.12 -m venv .venv-sam; then the installs in pipelines/sam_segment.py docstring
.venv-sam\Scripts\python.exe pipelines\tiling.py --country laos --mgrs-tile 48QUG
#   -> data/imagery/tiles/S2B_48QUG_20260112_0_L2A/ (191 chips; Sentinel-2 = disturbed-earth patches only)
.venv-sam\Scripts\python.exe pipelines\sam_segment.py --country laos --manifest data\imagery\tiles\S2B_48QUG_20260112_0_L2A\manifest.json --checkpoint data\models\sam3.1\sam3.1_multiplex.pt
#   -> data/imagery/sam/<scene_id>/detections.geojson (blocked until the checkpoint file exists)

uv run python pipelines/osm_exposure.py --country laos   # works: OSM features/km2 -> zones.exposure
uv run python pipelines/scoring.py --country laos       # works: deterministic ranking -> local DB (Laos ranks 4/18 today; a NULL component stays unscored)
# Repeat with --country cambodia. Same code path — that is the portability proof.
```

## 6. Run the demo

```bash
# Spark agent and Glimmer triage both read demo/cached-responses/ first:
# the demo must work with the API unreachable. See docs/demo-script.md.
```

## 7. Tests

```bash
uv run pytest
```

Scoring is deterministic, so it gets unit tests first: same inputs → same score, components preserved, surveyed zones deprioritized. Model outputs get smoke tests (shape, CRS, non-empty), not exact-value tests.

## Adding a country

1. Copy `countries/laos.json` to `countries/<new>.json` and fill every field (see `countries/README.md`).
2. Add its GADM + OSM extracts and strike data under `data/`.
3. Run the pipelines with `--country <new>` — no code changes. If a code change is needed to add a country, that is a bug in the design; fix the design, not the country.
4. Add report templates under `agent/templates/<lang>/` if the country needs a new language.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Checksum failure in `download_data` | Partial download — re-run; downloads resume. If it persists, the source file changed; update the manifest, don't skip the check. |
| Scoring prints `0/N zones scored` | Expected for Vietnam (no OSM `exposure`, 0/63) and for any zone lacking a component — today `strike_density` is seeded 106/106, so the usual gap is `crater_evidence` (NULL on 97/106 zones). A NULL component means unscorable, never an imputed 0. Observed ranked: Laos 4/18, Cambodia 2/25, Vietnam 0/63. |
| `sam_segment.py` exits 2 with a checkpoint failure in `summary.json` | Expected until the gated checkpoint lands: request access at huggingface.co/facebook/sam3.1, `hf auth login`, place `sam3.1_multiplex.pt` in `data/models/sam3.1/`. The failure is recorded verbatim in `data/imagery/sam/<scene_id>/summary.json`; no substitute model is used. |
| WorldStrat download stalls / MD5 mismatch | The Zenodo stream truncates silently on long downloads; `download_worldstrat.py` now verifies length and auto-resumes (max 20 attempts), and only extracts after the MD5 matches. Re-run it; the tar resumes. |
| Glimmer slow on a laptop | Check GPU offload (`llama.cpp` layer count) and context size (4K) — see `field/prompts/README.md` when it lands. Below ~12 tok/s, use the pre-recorded triage clip. |
| Scores change after a data reload | A component column was dropped or a profile filter changed — diff the profile and the seed script before trusting new numbers. |
