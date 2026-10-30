# Session handoff — 2026-10-30 (owner stopping; supersedes the 2026-10-28 handoff)

Purpose: resume exactly where this session stopped. Read `INDEX.md`
first for navigation, then `TASKS.md`. Verified by direct observation
(test runs, API calls, read-only SQL) on 2026-10-28..30 unless marked.

## TL;DR

- **Uncommitted work exists** (see Git below): the Oct 30 SAM-API +
  live-Spark changes. Everything from Oct 28-29 is committed
  (HEAD `4127889`).
- **META_API_KEY is set** in the repo-root `.env` (gitignored, verified
  ignored) and authenticates: `/health` reports
  `meta_api_key_set: true`; the account lists 9 models incl.
  `sam-3.1` and `muse-spark-1.3`.
- **Live Spark works** (P0-4 done): `/explain` = seeded cache -> live
  Muse Spark on miss -> 501 only if neither can answer. First live
  call (LAO.18_1) answered honestly from stored components.
- **SAM via API works mechanically, detects ~nothing** on Sentinel-2
  (P1-2): `--backend api` smoke clean, 0 detections; only hit in
  diagnostics was a whole-chip mask (now dropped by a >90% guard).
  Do not scale to 191 chips expecting craters. Local checkpoint still
  absent (`data/models/sam3.1/`), local backend never run live.
- Tests: **118 passed, 4 failed** — all 4 are machine-state, not code
  (below).

## Done Oct 28-30 (this machine)

1. **Sentinel-2 catalog complete**: 630,318 scenes (LA/KH/UA x
   L1C/L2A), counts identical to STAC `numberMatched`, 0 dupes.
   `data/sentinel2/catalog/` + `scripts/sentinel2_catalog.py`
   (crash-resilient per-slice; a 502 used to kill the run).
2. **KH-9 crater coordinates**: `data/kh9/bomb_coordinates.csv.gz` +
   `.geojson` — 541,397 craters, 99.996% pointing at valid photo
   pixels (`scripts/kh9_match.py`, QA overlays in `data/kh9/qa/`).
   Two seed_db bugs fixed en route (GeoJSON lone-`{` crash; STRtree
   `covers` -> 0 craters seeded silently). Docs: `docs/kh9-coordinates.md`.
3. **Building footprints**: `pipelines/building_exposure.py` seeded
   `zones.building_density` for all 106 zones (Laos 1.70M, Cambodia
   3.87M, Vietnam 23.9M buildings; r vs exposure 0.73/0.88). GUI
   overlay live (`/buildings/{country}`, viewport-bbox binary points).
4. **GUI**: satellite basemap default (Esri `/export` EPSG:4326, EOX
   fallback, Satellite toggle), Buildings toggle, translucent zones.
5. **WorldStrat**: 77/77 chips extracted, MD5-verified (`data/worldstrat/`).
6. **KH-9 frames**: 10 Edinburgh 8 m/px frames (`data/kh9/`).
7. **Research**: 10 subagent reports distilled in
   `docs/bomb-finding-research.md` (methods, IMAS doctrine, dud
   modelling rules) + imagery shortlists (CBERS-4A 2 m CC-BY STAC,
   NICFI via GEE, ESA TPM proposal, WD-CD/TAT-11 validation;
   TAT-11 zip downloaded to `data/validation/tat11/`, uninspected).
8. **Organization**: `INDEX.md` + folder READMEs + `scripts/filemap.py`
   (`--check` passes). no-ai-slop skill vendored in `.opencode/skills/`.

## Machine state (THIS machine — the other machine differs)

| Area | State |
|---|---|
| DB `data/clearfield.db` | zones 106; craters 541,397; crater_evidence 9 zones; exposure LA/KH only (43); **strike_density 0/106 (no THOR CSV here)**; building_density 106/106; ranked 0 |
| Other machine's DB | THOR seeded, exposure incl. Vietnam, 9 ranked (their `test_*` state) |
| SAM checkpoint | absent; HF approval still needed for local backend |
| THOR CSV | absent here; manual data.world download or copy from other machine -> `data/thor/THOR_Vietnam_7_31_2013.csv`, then `scripts/seed_thor.py` + scoring |
| Servers at stop | backend :8000 (`uv run --env-file .env uvicorn ...`), dashboard :8765 — both background shells of this session; restart with the same commands if dead |

## The 4 failing tests (all machine-state)

`test_real_db_zones_smoke`, `test_cached_explanations.py` x3 — they
assert a THOR-seeded/Vietnam-exposed DB. On this DB the seeded
explanation cache is correctly judged stale (503). They pass on the
other machine. Fix = data sync (above), not code.

## Uncommitted (commit these first)

`Start-ClearField.bat` (.env loading), `agent/spark.py` (live Spark),
`backend/app/main.py` (/explain live path), `pipelines/sam_segment.py`
(API backend), `tests/test_api.py` (updated /explain semantics),
`tests/test_spark.py` (new), `TASKS.md`, `docs/architecture.md`.

## Suggested order when you return

1. Commit the uncommitted batch above.
2. THOR CSV onto this machine -> `seed_thor.py` -> scoring -> this
   machine reaches 9 ranked zones and the suite goes green;
   `scripts/make_cached_explanations.py` regen if components change.
3. Crater route (not SAM-on-Sentinel-2): Barthelme U-Net tile-level
   reproduction from `data/barthelme/data.zip` (recipe in
   `docs/kh9-coordinates.md`), then EarthExplorer KH-9 frame search
   for Xiangkhoang (orthorectification is the long pole, 3-8 weeks).
4. Quick imagery wins: CBERS-4A STAC catalog for demo provinces;
   NICFI (GEE) archival for Laos/Cambodia; inspect
   `data/validation/tat11/` inner data.zip.
5. GUI next layers (scoped, not built): crater points (`/craters`),
   THOR points (`seed_thor --points` export + `/strikes`), zone/place
   labels, KH-9 footprints. See chat 2026-10-29 for the asset list.
6. Housekeeping: `stageb_*.py` at repo root are one-off diagnostics —
   delete or move under `scripts/`. `scripts/download_oam.py` is
   written but its full download was never run.
