# ClearField

**A clearance-prioritization platform for bombed countries.** ClearField fuses declassified bombing records with satellite imagery and human geography to rank which land should be surveyed and cleared first, explains every ranking in plain language, and lets field workers record new finds offline — built once, reusable in any bombed country by swapping a data profile.

> Project status: scaffold + first data tranche (Oct 27, 2026). In place and tested: repo structure, country profiles, schemas, deterministic scoring, `/zones` + `/finds` over the local DB, and a seeded database (106 GADM zones; 541,397 real Barthelme craters; 9 zones with crater evidence; OSM exposure computed for all 18 Laos + 25 Cambodia zones by `pipelines/osm_exposure.py`). No zone is rankable yet — strike density (THOR) has not landed, so scoring still correctly scores 0 zones; `META_API_KEY` is still to be provided, and there are no live model calls. Barthelme coverage (lat 14.17–17.03) does not reach the Laos demo province Xiangkhoang. Details: [`WORKFLOW_SYNTHESIS.md`](WORKFLOW_SYNTHESIS.md). This README describes the target state.

## The problem

Laos is the most heavily bombed country per capita in history — 1,041,519 recorded US bombing missions (USAF THOR), much of it unexploded still. Clearance teams don't have a detection problem; they have a math problem: far more suspect land than survey capacity. The question is never "is there UXO here?" but "where do we go first?" Cambodia (144,944 missions in the same archive), Vietnam, WWII Europe, and modern conflict zones all share that bottleneck.

## What it does

1. **A ranked priority map.** Zones ranked by a deterministic, auditable formula: THOR strike density × crater evidence from satellite imagery × proximity to villages, farmland, schools, and roads (OpenStreetMap), minus land already surveyed. Same inputs, same score, every component stored.
2. **A bilingual query and reporting agent.** Ask in English, Lao, or Khmer — "which unsurveyed areas near farmland in Xiangkhoang are highest priority, and why?" — and get a map plus a briefing citing the real score components, never invented numbers. It also generates structured survey reports from templates.
3. **Offline field triage.** A worker photographs a find, records GPS and Lao notes with no connectivity, and a local model turns it into a structured record in the same database. It syncs when connectivity returns and becomes new evidence for the ranking.

## How it works

```
THOR + imagery + OSM ──► SAM 3.1 segments craters (cached, never re-run)
                      ──► PostGIS code scores zones (deterministic)
                      ──► Muse Spark explains + reports (EN / Lao / Khmer)
Field photo + GPS ────► Muse Glimmer, offline ──► record syncs to PostGIS
```

One job per model: **SAM sees, code scores, Spark explains, Glimmer captures offline.** No model does another model's job, and no model invents a score. Full architecture: [`docs/architecture.md`](docs/architecture.md).

## Multi-country by design

Country is a configuration, never code. Everything country-specific lives in one profile under [`countries/`](countries/) (strike source/filter, imagery set, boundaries, OSM extract, stats source, languages). Demo scope: **Laos (Xiangkhoang) + Cambodia (Tbong Khmum)**. Cambodia and Vietnam are nearly free (same THOR file, same ordnance); WWII Europe needs re-validation; modern conflicts (Ukraine, Colombia, Angola, Bosnia) swap in UCDP/ACLED + UNOSAT data.

## What it is not

- **Not a robot.** A robotics layer was evaluated and dropped — it didn't fit the hardware or the build window.
- **Not a clearance tool.** It prioritizes survey and clearance; humans clear, and anything ambiguous escalates to a human operator.
- **Not dependent on gated data.** Official hazard polygons live in national IMSMA databases behind operator accreditation, everywhere. ClearField is built entirely on public data and gets better with a partnership, not blocked without one.

## Getting started

Full guide: [`docs/getting-started.md`](docs/getting-started.md). Short version:

```powershell
git clone <repo-url> clearfield; cd clearfield
Copy-Item .env.example .env   # fill in META_API_KEY when available
uv sync                       # project-local Python env (.venv)
scripts\download_data.ps1 predictions.zip tables.zip README.txt gadm41_LAO_1.json gadm41_KHM_1.json gadm41_VNM_1.json laos-261025.osm.pbf cambodia-261025.osm.pbf
scripts\seed_db.ps1           # ~65 min: GADM zones + Barthelme craters -> data/clearfield.db (SQLite)
uv run python pipelines/osm_exposure.py --country laos   # OSM exposure per zone (repeat: cambodia)
uv run pytest
uv run uvicorn backend.app.main:app --reload   # API on :8000, open frontend/index.html
uv run python pipelines/scoring.py --country laos   # scores 0 until THOR lands (by design)
# DB target schema: db/schema.sql (PostGIS); runtime today: db/schema.local.sql (SQLite).
```

## Data

All datasets are public and reproduced by [`scripts/download_data.sh`](scripts/download_data.sh) (Python implementation, `.ps1` twin); nothing under `data/` is committed. Barthelme files are MD5-verified; GADM publishes no checksum (local MD5s recorded in the manifest). Barthelme and OSM (Geofabrik) downloads are pinned and MD5-checked; THOR, UXOTi_NPA, and AMLID are not pinned yet. Sources and licenses: [`docs/data-manifest.md`](docs/data-manifest.md).

## Demo

Scripted demo (three moments: country switch, bilingual "why #3?", offline triage): [`docs/demo-script.md`](docs/demo-script.md). Every demo response is pre-cached under `demo/cached-responses/` so the demo survives an API outage.

## License

Code in this repo is MIT. Datasets keep their own licenses (see `docs/data-manifest.md`).
