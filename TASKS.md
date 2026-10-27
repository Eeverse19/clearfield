# ClearField — Task Board

Generated 2026-10-27 from a 7-agent workflow audit (inventory, docs, code
health, backlog, git hygiene, adversarial critic, synthesis), with every
load-bearing claim re-verified by hand. Effort: S < 1 day, M = a few days,
L = a week+. P0 blocks the first ranked demo; P1 is core-feature work;
P2 is stretch/polish.

**Where the project actually is:** scaffold + first data tranche. 106 GADM
zones and 541,397 Barthelme craters are seeded; OSM exposure is computed
for all Laos + Cambodia zones; `/zones` and `/finds` work; 32 tests pass
(`.venv\Scripts\python.exe -m pytest -q` → 32 passed, 2026-10-27).
**No zone is rankable yet**: `strike_density` is NULL on 106/106 zones,
so `pipelines/scoring.py` correctly scores 0. The THOR data needed to fix
that is already on disk — only the ingestion code is missing (P0-1).

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

- [ ] **P0-1. Implement the THOR `strike_density` seed. (M)**
  A complete, parent-ready spec already exists: `docs/thor/thor_final_spec.md`
  (rescued from `.uv-tmp`; see `docs/thor/README.md`). Deliverables per spec:
  new `scripts/seed_thor.py` (+ `.ps1`/`.sh` wrappers), profile edits in
  `countries/{laos,cambodia,vietnam}.json:8-9` (dataset →
  `data/thor/THOR_Vietnam_7_31_2013.csv`, `country_filter` string → list —
  **do not rename the CSV**), point-in-zone assignment, and the doc edits in
  `docs/thor/thor_doc_edits.md`. Expected result (from the scan):
  strike_density populated for all 106 zones; top density Quang Tri
  ≈ 54.8 missions/km², Laos top Savannakhet ≈ 15.83. Then
  `pipelines/scoring.py:26` finally ranks zones instead of scoring 0.
  Also fixes the stale claim at `README.md:5` ("THOR has not landed" — the
  file landed; the pipeline hasn't).
- [ ] **P0-2. Build the map UI. (M)** `frontend/index.html` is still the
  scaffold placeholder ("The map lands with the first real ranking") and
  its text is stale — it claims OSM exposure hasn't landed, but it has for
  Laos + Cambodia. Needs P0-1 for real rankings; can be built against
  `/zones` today.
- [ ] **P0-3. Commit the work in progress and restore the remote. (S)**
  The repo has exactly one commit (`664bacb Project creation`), the
  upstream `origin/main` is **gone** (remote:
  `https://github.com/Eeverse19/clearfield.git`), and substantial work is
  uncommitted: 9 modified tracked files (`.gitignore`, `README.md`,
  `countries/*`, `data/README.md`, `docs/data-manifest.md`,
  `docs/getting-started.md`, `scripts/download_data.py`) plus untracked
  `pipelines/osm_exposure.py` and `tests/test_osm_exposure.py` — and now
  `docs/thor/` + this file. Commit in logical chunks, then re-push `main`.
- [ ] **P0-4. Wire `/explain` (cache-first, then live Spark). (M)**
  `backend/app/main.py:188-195` returns 501 both ways today;
  `agent/spark.py:9` raises `NotImplementedError` ("cache-first path lands
  first"). `demo/cached-responses/` contains only a README, so the cached
  demo path (`docs/demo-script.md`) has nothing to serve yet either.
  Blocked on `META_API_KEY` for live calls only — cache-first needs P0-1.
- [ ] **P0-5. Pick the Cambodia demo province. (S, after P0-1)**
  `countries/cambodia.json:16` `_todo`: "pick one province from THOR
  density once the csv is available" — it now is. Pure-THOR top candidate
  from the scan: Tbong Khmum (KHM.25_1, ≈ 6.37 missions/km²). Set
  `demo_area` once densities are seeded.

## P1 — core features still stubbed

- [ ] **P1-1. `pipelines/tiling.py` — imagery → 256×256 tiles. (M)**
  Scaffold stub (`pipelines/tiling.py:1`).
- [ ] **P1-2. `pipelines/sam_segment.py` — SAM 3.1 masks → GeoJSON, cached. (L)**
  Scaffold stub (`pipelines/sam_segment.py:3`). "SAM sees only."
- [ ] **P1-3. `field/triage.py` — offline Glimmer triage. (L)**
  Stub raising `NotImplementedError` (`field/triage.py:11`).
- [ ] **P1-4. Report templates for Khmer and Lao. (M)**
  `agent/templates/km/` and `agent/templates/lo/` contain only `.gitkeep`;
  only `agent/templates/en/survey-report.md` exists. Vietnamese templates
  don't exist either (`countries/vietnam.json` `_todo`).
- [ ] **P1-5. Fill `demo/cached-responses/` for the scripted demo. (S, after P0-1/P0-4)**
  `docs/demo-script.md` promises every demo response is pre-cached; the
  folder holds only a README.
- [ ] **P1-6. Vietnam OSM exposure. (S)** Only Laos + Cambodia `.osm.pbf`
  extracts are in `data/osm/`, so 63 Vietnam zones have no exposure yet.
  Pin the extract URL/checksum in `docs/data-manifest.md`
  (`countries/vietnam.json` `_todo`).
- [ ] **P1-7. Barthelme coverage gap for the Laos demo. (M)**
  Crater predictions cover lat 14.17–17.03 and don't reach Xieng Khouang
  (`README.md:5`), so the demo province has no crater evidence. Decide:
  new imagery/predictions for Xieng Khouang, or move the demo area.
- [ ] **P1-8. PostGIS target. (M)** Runtime is SQLite
  (`db/schema.local.sql`); `db/schema.sql` (PostGIS) is the target.
  Migration path + `DATABASE_URL` wiring per `docs/architecture.md`.

## P2 — stretch, polish, hygiene

- [ ] **P2-1. Pin UXOTi_NPA + AMLID downloads. (S)**
  `scripts/download_data.py:92` TODO (Figshare 21688673, Zenodo 18001447);
  `README.md:57` notes THOR/UXOTi/AMLID are unpinned.
- [ ] **P2-2. Update stale status text after P0-1 lands. (S)**
  `README.md:5`, `docs/getting-started.md:5`, `frontend/index.html`,
  `frontend/README.md:4` all describe the pre-THOR state. The exact edits
  are pre-written in `docs/thor/thor_doc_edits.md`.
- [ ] **P2-3. Replace manifest mission counts with observed counts. (S)**
  `docs/data-manifest.md:31` claims (Laos 1,041,519 etc.) are all low vs
  the actual CSV scan — observed table is in `docs/thor/thor_final_spec.md` §0.
- [ ] **P2-4. Stale `.pytest_cache` `lastfailed` entry** names
  `tests/test_api.py::TestClient`; the suite passes clean (32 passed,
  2026-10-27). No action beyond the next test run overwriting it.
- [ ] **P2-5. Vietnam profile completion** (`countries/vietnam.json` `_todo`):
  unset `demo_area`, NORTH+SOUTH VIETNAM `TgtCountry` mapping (folded into
  P0-1's list-shaped `country_filter`; note `VIETNAM` as a value occurs
  zero times in the CSV).

---

## Folder map (after the 2026-10-27 tidy)

```
agent/        Spark explain/report agent (stub) + report templates (en only)
backend/      FastAPI app — /health /countries /zones /finds work; /explain 501
countries/    laos/cambodia/vietnam profiles (dataset name fixed by P0-1)
data/         gitignored datasets + clearfield.db (788 MB seeded SQLite)
  thor/       canonical THOR csv (2.5 GB)
db/           schema.local.sql (runtime SQLite), schema.sql (PostGIS target)
demo/         cached-responses/ — currently just a README (P1-5)
docs/         architecture, data-manifest, demo-script, getting-started
  thor/       NEW: strike-density specs + scan evidence (rescued from .uv-tmp)
field/        offline triage (stub)
frontend/     placeholder page — map UI is P0-2
pipelines/    scoring.py (works, starved of THOR), osm_exposure.py (works),
              tiling.py + sam_segment.py (stubs)
scripts/      download_data.* / seed_db.* (seed_thor.* lands with P0-1)
tests/        5 files, 32 tests, all passing
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
