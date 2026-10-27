# Getting started

Target audience: a developer (or a future contributor) setting ClearField up from scratch. Estimated time once the pieces exist: ~30 minutes plus download time.

> Status (Oct 27, 2026): sections 1, 2 (pinned files only), 3 (SQLite seed), 4, and 7 work today; the local DB is seeded (106 zones, 541,397 craters; OSM exposure for Laos + Cambodia). Section 5: `osm_exposure.py` + `scoring.py` work; scoring correctly scores 0 zones until THOR lands; `tiling.py`/`sam_segment.py` are still stubs. `META_API_KEY` is still to be provided. Full audit: [`../WORKFLOW_SYNTHESIS.md`](../WORKFLOW_SYNTHESIS.md).

## Prerequisites

- Python 3.11+ via `uv` (manages the project-local `.venv`; on this Windows machine `uv sync` is the only setup step)
- PostgreSQL 15+ with PostGIS (target DB; the scaffold runs on the SQLite mirror in `db/schema.local.sql` first)
- A Meta Model API key (dev.meta.ai) for Spark + SAM 3.1 — put it in `.env`, never in code
- ~1 GB free disk for today's footprint (seeded DB ≈826 MB + predictions.zip 48 MB); ~8 GB if Barthelme `data.zip`/`models.zip` and THOR are also fetched
- Optional: Modal account (SAM batch runs), a GPU machine for local Glimmer testing

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
- **THOR** (`thor_data_vietnam.csv`, ~1.5 GB): create a free account at data.world, download from data.world/datamil/vietnam-war-thor-data, place the file in `data/thor/`.
- **Raw KH-9 scans** (if you want them): free USGS EROS account at earthexplorer.usgs.gov, Declassified Data > Declass 3 collection. The georeferenced Barthelme versions (Edinburgh DataShare ds/7682, ds/7683) cover the demo areas and need no account.

## 3. Database

```powershell
# Today (SQLite mirror; PostGIS schema in db/schema.sql is the target, not yet wired):
scripts\seed_db.ps1   # ~65 min: GADM zones + Barthelme craters -> data/clearfield.db
# Loads NO OSM/THOR yet: strike_density and exposure stay NULL, so scoring ranks 0 zones.
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

```bash
uv run python pipelines/tiling.py --country laos        # stub: imagery -> 256x256 tiles
uv run python pipelines/sam_segment.py --country laos   # stub: SAM 3.1 -> masks -> GeoJSON, cached
uv run python pipelines/osm_exposure.py --country laos   # works: OSM features/km2 -> zones.exposure
uv run python pipelines/scoring.py --country laos       # works: deterministic ranking -> local DB (0 scored until THOR)
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
| Scoring prints `0/N zones scored` | Expected until THOR (`strike_density`) and OSM (`exposure`) are seeded — a NULL component means unscorable, never an imputed 0. |
| `SAM` calls slow / rate-limited | Demo provinces are pre-computed and cached; live API is only for one tile. See `docs/demo-script.md`. |
| Glimmer slow on a laptop | Check GPU offload (`llama.cpp` layer count) and context size (4K) — see `field/prompts/README.md` when it lands. Below ~12 tok/s, use the pre-recorded triage clip. |
| Scores change after a data reload | A component column was dropped or a profile filter changed — diff the profile and the seed script before trusting new numbers. |
