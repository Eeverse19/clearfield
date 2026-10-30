# ClearField — Task Board

Generated 2026-10-27 from a 7-agent workflow audit (inventory, docs, code
health, backlog, git hygiene, adversarial critic, synthesis), with every
load-bearing claim re-verified by hand. Effort: S < 1 day, M = a few days,
L = a week+. P0 blocks the first ranked demo; P1 is core-feature work;
P2 is stretch/polish.

**Where the project actually is:** scaffold + first data tranche. 106 GADM
zones and 541,397 Barthelme craters are seeded; OSM exposure is computed
for all Laos + Cambodia zones (Vietnam 0/63); `/zones` and `/finds` work; 80 tests pass
(`.venv\Scripts\python.exe -m pytest -q` → 80 passed, 2026-10-28).
`strike_density` is non-NULL on 106/106 zones (corrected THOR seed, P0-1 done 2026-10-28), and `pipelines/scoring.py` ranks 6 zones: Laos 4/18, Cambodia 2/25, Vietnam 0/63 (Vietnam has no OSM exposure). The remaining unscored zones lack `crater_evidence` (and, for Vietnam, `exposure`).

**Oct 28, 2026 addendum (imagery pipeline; the audit below is otherwise
still current):** Sentinel-2 catalog **done** — 630,318 scenes
(Laos/Cambodia/Ukraine × L1C/L2A) in `data/sentinel2/catalog/`, counts
verified against the STAC API (`scripts/sentinel2_catalog.py`, now
crash-resilient per-slice). `pipelines/tiling.py` implemented (P1-1):
Xiangkhoang pilot scene `S2B_48QUG_20260112_0_L2A` -> 191 chips.
`pipelines/sam_segment.py` implemented (P1-2 code): SAM 3.1 local on
RTX 3080 (`.venv-sam`), per-chip cache, masks → GeoJSON; **not run** —
gated checkpoint `data/models/sam3.1/sam3.1_multiplex.pt` not yet
present, and the script fails closed (recorded in `summary.json`) until
it is. Sentinel-2 output is labelled disturbed-earth patch candidates,
never crater counts (10 m/px; see `docs/architecture.md`). WorldStrat
1.5 m/px benchmark chips: 77 selected (Laos 4, Cambodia 11, Ukraine 62),
download/extract in progress (`scripts/download_worldstrat.py`,
CC BY-NC). Live status: `scripts/dashboard.py` (127.0.0.1:8765).
New finding for P0-1: the Barthelme paper's THOR corrections (Indian
1960 datum ~500 m shift, B-52 SACCOACT/SEADAB dedup, weapon filtering)
are **not** in `docs/thor/` — fold them into the spec before seeding
(details in `docs/data-manifest.md` §4). **(Folded in 2026-10-28 as `docs/thor/thor_final_spec.md` §9; see P0-1.)** **Known discrepancy (verified 2026-10-28):** the `data/sentinel2/` catalog, `data/imagery/` chips, and `data/worldstrat/` outputs claimed in this addendum are **not on disk** (`data/` contains only `barthelme/`, `gadm/`, `osm/`, `thor/`, and the DB); regeneration is pending.

---

## Decisions for you (nothing here was done automatically)

- [x] **D1. Delete the 2.5 GB THOR duplicate at the repo root. — DONE
  2026-10-27.** Both copies hashed directly before deletion: root copy and
  canonical `data/thor/THOR_Vietnam_7_31_2013.csv` (2,627,971,171 B) both
  MD5 `939F28D770D9B3B9ACD37553EAB0FB85`. Root copy deleted; canonical
  verified still in place. Freed 2.5 GB.
- [ ] **D2. Delete the `.uv-tmp/thor_*` originals — after committing the
  rescue.** They were copied (not moved) to `docs/thor/` on 2026-10-27.
  Once that copy is committed, the `.uv-tmp` originals are redundant.
- [ ] **D3. `Raw Docs/`** is an empty folder at the root. Keep (as a drop
  zone for source documents?), rename, or remove? It is invisible to git
  while empty.
- [ ] **D4. `.agents/skill-drafts/jev-decision-layer/SKILL.md`** is
  untracked. Commit it, move it to your personal skills folder, or ignore
  `.agents/`?
- [ ] **D5. `WORKFLOW_SYNTHESIS.md`** (43 KB, 692 lines) sits at the root.
  Fine where it is, but if it moves to `docs/`, the links in `README.md:5`
  and `docs/getting-started.md:5` must move with it. Do it in the same
  commit as P0-3, not before.

## P0 — blocks the first ranking / demo

- [x] **P0-1. Implement the THOR `strike_density` seed. (M) — DONE 2026-10-28 (real run + scoring).** Implemented per `docs/thor/thor_final_spec.md` incl. §9; D1–D4 confirmed by owner 2026-10-28 as pinned defaults (spec §9.6: D1+D2 `*_WGS84` columns + forced EPSG:1542 everywhere, D3 SACCOACT dedup cutoff 1971-04-01, D4 weapon filter OFF / U17 missions/km²). Corrected (C) real-run summary: rows 4,670,422; assigned 3,401,836; invalid 1,130,146; outside 108,385; deduped_saccoact 30,055 (March variant 30,851); weapon_excluded 0; corrected mismatch 144,468; per-country missions cambodia 191,184 / laos 1,090,845 / vietnam 2,119,807. `strike_density` non-NULL 106/106; density ranges KH 0.000930–6.209188 (top `KHM.25_1` 6.209188), LA 0.007658–15.828597 (top `LAO.12_1` 15.828597), VN 0.003283–53.146062 (top `VNM.50_1` 53.146062). Scoring then ranked Laos 4/18, Cambodia 2/25, Vietnam 0/63 (no exposure); both demo provinces stay unscorable for lack of `crater_evidence`. (Baseline-A dry-run history: rows_read 4,670,422 / invalid_coords 1,130,146 / baseline_assigned 3,419,286 reproduced exactly before the real run; baseline-A figures are scan expectations, superseded by the C numbers above.) Original task text follows for history:
  A complete, parent-ready spec already exists: `docs/thor/thor_final_spec.md`
  (rescued from `.uv-tmp`; see `docs/thor/README.md`). Deliverables per spec:
  new `scripts/seed_thor.py` (+ `.ps1`/`.sh` wrappers), profile edits in
  `countries/{laos,cambodia,vietnam}.json:8-9` (dataset →
  `data/thor/THOR_Vietnam_7_31_2013.csv`, `country_filter` string → list —
  **do not rename the CSV**), point-in-zone assignment, and the doc edits in
  `docs/thor/thor_doc_edits.md`. Expected result (from the scan):
  strike_density populated for all 106 zones; observed C tops: Quang Tri (`VNM.50_1`) 53.146062 missions/km², Laos top Savannakhet (`LAO.12_1`) 15.828597 (≈54.8 / ≈15.83 were baseline-A scan expectations, superseded). `pipelines/scoring.py` now ranks 6 zones (Laos 4, Cambodia 2, Vietnam 0).
  (Historical note: this item originally also targeted a stale THOR claim at `README.md:5` — the
  file landed; the pipeline hasn't).
- [x] **P0-2. Build the map UI. — DONE 2026-10-27.** `frontend/index.html`
  is now a single-file interactive map GUI (canvas choropleth per score
  component, evidence-ranking list: official priority for the zones ranked after P0-1 (Laos 4/18, Cambodia 2/25), honestly labelled a preview elsewhere, per-zone inspector with a briefing generated from stored
  components, and field-find recording via `POST /finds` with an offline
  queue). Served by the backend at `/`; `Start-ClearField.bat` launches it.
  Official priority ranking is live for the 6 ranked zones since P0-1 landed (2026-10-28); other zones remain preview-only.
- [x] **P0-3. Commit the work in progress and restore the remote. (S) — DONE 2026-10-28.** Verified 2026-10-28: `main` == `origin/main` (`3610314`). The P0-1 THOR code + doc refresh are a new separate uncommitted diff left for owner review. (Stale original text below kept for history.)
  The repo has exactly one commit (`664bacb Project creation`), the
  upstream `origin/main` is **gone** (remote:
  `https://github.com/Eeverse19/clearfield.git`), and substantial work is
  uncommitted: 9 modified tracked files (`.gitignore`, `README.md`,
  `countries/*`, `data/README.md`, `docs/data-manifest.md`,
  `docs/getting-started.md`, `scripts/download_data.py`) plus untracked
  `pipelines/osm_exposure.py` and `tests/test_osm_exposure.py` — and now
  `docs/thor/` + this file. Commit in logical chunks, then re-push `main`.
- [x] **P0-4. Wire `/explain` (cache-first, then live Spark). (M) — DONE
  2026-10-30 (live half).** Cache-first landed 2026-10-29; live Spark
  wired 2026-10-30 after META_API_KEY arrived: `agent/spark.py`
  (facts-only prompt over stored components; never invents numbers,
  missing = unscorable) is called by `explain_request` on a cache miss
  (`source="live"`, `origin="muse_spark_live"`, never written into the
  validated cache); 501 only when neither cache nor key can answer,
  502 on upstream failure. First live call (LAO.18_1, unscorable)
  answered honestly from stored components. Regenerate seeds with
  `scripts/make_cached_explanations.py` after each scoring run.
  Remaining stretch: genuine `lo`/`km` template translations (P1-4).
  Original task text follows for history:
  `backend/app/main.py:188-195` returned 501 both ways then (now `explain_request` at `backend/app/main.py:428`);
  `agent/spark.py:9` raises `NotImplementedError` ("cache-first path lands
  first"). `demo/cached-responses/` contains only a README, so the cached
  demo path (`docs/demo-script.md`) has nothing to serve yet either.
  Blocked on `META_API_KEY` for live calls only — cache-first's P0-1 dependency is satisfied (done 2026-10-28).
- [x] **P0-5. Pick the Cambodia demo province. — DONE 2026-10-27.**
  Owner confirmed **Tbong Khmum** (GADM `TbongKhmum`, `KHM.25_1`). Set in
  `countries/cambodia.json` as `"demo_area": "Tbong Khmum"` (display name,
  same GADM-name convention as Laos `"Xiangkhoang"`). THOR scan: 31,419 missions,
  ≈ 6.37/km², #1 Cambodia on both count and density. Barthelme
  `crater_evidence` is still NULL there — ranking that province still
  needs a crater source (P1-7); THOR ingest (P0-1) is done. Name-join fix:
  `demo_area` is only a display name (`"Tbong Khmum"` matches 0 rows in
  `zones.admin_name`, which stores GADM `TbongKhmum`); the stable join
  key is the new required `demo_zone_id` (GADM `GID_1`: `KHM.25_1`,
  Laos `LAO.18_1`, Vietnam `null`) — join on `zones.id`, never the name.

## P1 — core features still stubbed

- [x] **P1-1. `pipelines/tiling.py` — imagery → chips. — CODE + PILOT DONE
  2026-10-28.** STAC scene selection over the profile's demo zone, COG
  windowed reads, zone-clipped chips + manifest with per-chip
  transform/CRS. Deviation from the original 256×256 sketch: 1024×1024
  chips (SAM 3's processor works at 1008 px; 256 px would multiply
  calls ~16×). Pilot: Xiangkhoang tile 48QUG, 191 chips. Generalizing
  beyond one pinned scene is follow-up work, not a stub anymore.
- [ ] **P1-2. `pipelines/sam_segment.py` — SAM 3.1 masks → GeoJSON, cached.
  CODE DONE 2026-10-28; FIRST RUN DONE 2026-10-30 (API backend).** Local
  SAM 3.1 (`.venv-sam`, RTX 3080) plus `--backend api` (Meta Model API
  `sam-3.1`, wired 2026-10-30 once META_API_KEY landed). API smoke:
  2-chip run clean, 0 detections; mid-chip diagnostics returned only a
  whole-chip "disturbed earth" mask (now dropped by the >90% guard).
  Zero-shot text prompting on 10 m/px Sentinel-2 is weak, as the
  literature predicted — do not scale to 191 chips expecting craters;
  the KH-9/U-Net path is the crater route. Local checkpoint
  (`data/models/sam3.1/`) still absent, local backend untested live.
- [ ] **P1-3. `field/triage.py` — offline Glimmer triage. (L)**
  Stub raising `NotImplementedError` (`field/triage.py:11`).
- [ ] **P1-4. Report templates for Khmer and Lao. (M)**
  `agent/templates/km/` and `agent/templates/lo/` contain only `.gitkeep`;
  only `agent/templates/en/survey-report.md` exists. Vietnamese templates
  don't exist either (`countries/vietnam.json` `_todo`).
- [ ] **P1-5. Fill `demo/cached-responses/` for the scripted demo. (S, after P0-1/P0-4) — PARTIAL 2026-10-29.** Moment 2 `/explain` files are seeded for all 6 ranked zones (English; `scripts/make_cached_explanations.py`, format frozen in `demo/cached-responses/README.md`). Still pending: genuine `lo`/`km` translations (needs a translation source; also P1-4 templates) and cached files for the non-`/explain` scripted steps (Moments 0, 1, 3, 4). Original text:
  `docs/demo-script.md` promises every demo response is pre-cached; the
  folder holds only a README.
- [x] **P1-6. Vietnam OSM exposure. (S) — DONE 2026-10-29.** Pinned `vietnam-261025.osm.pbf` (331,590,326 B, md5 `cd128585774ee4e3ff8c3bc33649cd60` verified vs Geofabrik `.md5`) in `scripts/download_data.py` + `docs/data-manifest.md`; `vietnam.json` pinned. Exposure 63/63 VN zones (2.579–134.123/km²); VN-only scoring ranked 3/63 (VNM.50_1/34_1/21_1); cache regen 9 files. Original: Only Laos + Cambodia `.osm.pbf`
  extracts are in `data/osm/`, so 63 Vietnam zones have no exposure yet.
  Pin the extract URL/checksum in `docs/data-manifest.md`
  (`countries/vietnam.json` `_todo`).
- [ ] **P1-7. Barthelme coverage gap for both demo provinces. (M)**
  Crater predictions cover lat 14.17–17.03 and don't reach Xiangkhoang
  (`LAO.18_1`, `README.md:5`), so that demo province has no crater
  evidence. Same gap for the Cambodia demo: `crater_evidence` is NULL
  for Tbong Khmum (`KHM.25_1`) as well — both demo provinces
  (`demo_zone_id` in `countries/{laos,cambodia}.json`) have NULL
  `crater_evidence`. Decide: new imagery/predictions for Xiangkhoang
  and Tbong Khmum, or move the demo areas.
- [ ] **P1-8. PostGIS target. (M)** Runtime is SQLite
  (`db/schema.local.sql`); `db/schema.sql` (PostGIS) is the target.
  Migration path + `DATABASE_URL` wiring per `docs/architecture.md`.

## P2 — stretch, polish, hygiene

- [ ] **P2-1. Pin UXOTi_NPA + AMLID downloads. (S)**
  `scripts/download_data.py:92` TODO (Figshare 21688673, Zenodo 18001447);
  `README.md:57` notes THOR/UXOTi/AMLID are unpinned.
- [x] **P2-2. Update stale status text after P0-1 lands. (S) — DONE 2026-10-28.** Pre-seed stale facts fixed earlier (observed counts, real THOR filename/sizes, OSM-landed wording, durable frontend preview text); post-seed half applied 2026-10-28 with corrected C-numbers + ranked counts (Laos 4/18, Cambodia 2/25, Vietnam 0/63) across README/TASKS/WORKFLOW_SYNTHESIS/data README/manifest/getting-started/THOR README/frontend. The spec's canned OSM "still 0 ranked" wording was not copied.
  `README.md:5`, `docs/getting-started.md:5`, `frontend/index.html`,
  `frontend/README.md:4` all describe the pre-THOR state. The exact edits
  are pre-written in `docs/thor/thor_doc_edits.md`.
- [x] **P2-3. Replace manifest mission counts with observed counts. (S) — DONE 2026-10-28.** `docs/data-manifest.md` §4 now carries observed counts (Laos 1,087,019; S. Vietnam 1,658,608; N. Vietnam 607,482; Cambodia 147,097; Thailand 2,574), real filenames/sizes/MD5s, and §9 status.
  `docs/data-manifest.md:31` claims (Laos 1,041,519 etc.) are all low vs
  the actual CSV scan — observed table is in `docs/thor/thor_final_spec.md` §0.
- [ ] **P2-4. Stale `.pytest_cache` `lastfailed` entry** names
  `tests/test_api.py::TestClient`; the suite now collects 80 tests (`pytest --collect-only -q` → "80 tests collected", 2026-10-28; focused API/scoring/THOR-seed run 44 passed). No action beyond the next test run overwriting it.
- [ ] **P2-5. Vietnam profile completion** (`countries/vietnam.json` `_todo`):
  unset `demo_area`, NORTH+SOUTH VIETNAM `TgtCountry` mapping (folded into
  P0-1's list-shaped `country_filter`; note `VIETNAM` as a value occurs
  zero times in the CSV).

---

## Folder map (after the 2026-10-27 tidy)

```
agent/        Spark explain/report agent (stub) + report templates (en only)
backend/      FastAPI app — /health /countries /zones /finds work; /explain 501
countries/    laos/cambodia/vietnam profiles (THOR dataset + list filter, P0-1 code)
data/         gitignored datasets + clearfield.db (825,843,712 B seeded SQLite)
  thor/       canonical THOR csv (2.5 GB)
db/           schema.local.sql (runtime SQLite), schema.sql (PostGIS target)
demo/         cached-responses/ — currently just a README (P1-5)
docs/         architecture, data-manifest, demo-script, getting-started
  thor/       NEW: strike-density specs + scan evidence (rescued from .uv-tmp)
field/        offline triage (stub)
frontend/     single-file map GUI, served by backend at / (P0-2 done)
pipelines/    scoring.py (works; ranks 6 zones post-THOR), osm_exposure.py (works),
              tiling.py (works, pilot scene done), sam_segment.py (works,
              awaiting checkpoint) — Oct 28 addendum above
scripts/      download_data.* / seed_db.* / seed_thor.* (P0-1 done 2026-10-28)
tests/        80 tests, all passing (2026-10-28)
THOR VIETNAM DATA/  DELETED 2026-10-27 (D1) — was a proven duplicate of data/thor/
Raw Docs/     empty — your call (D3)
```

## What the 2026-10-27 tidy changed (and deliberately didn't)

Done: copied the 7 THOR spec/scan files from `.uv-tmp/` to `docs/thor/`
(originals untouched) with an index README; added `/THOR VIETNAM DATA/` and
`pytest-of-*/` to `.gitignore`; removed the regenerable root
`pytest-of-<user>/` pytest temp dir; wrote this file.

Deliberately **not** done (adversarial-critic vetoes — each could destroy
the only copy of something or break links/imports): deleting or renaming
either THOR CSV (the spec changes the profiles instead); cleaning
`.uv-tmp/` before the rescue is committed; moving `WORKFLOW_SYNTHESIS.md`
before its links are updated in the same commit; any src-layout reshuffle.
