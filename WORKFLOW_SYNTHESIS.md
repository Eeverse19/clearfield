# ClearField — merged implementation checklist (WORKFLOW_SYNTHESIS)

> Provenance / honest gap: the six prior workflow results named in the caller
> input arrived ONLY as handoff gaps ("result belongs to another parent Run or
> Workflow", labels 1–6, `reads: []`, summaries "structured result submitted").
> No prior evidence text was readable in this run. Winner: the gap markers.
> Everything below was therefore re-derived first-hand on 2026-10-26 from the
> workspace at the repo root: full reads of
> code/tests/docs, read-only SQLite queries against `data/clearfield.db`,
> source-file counts inside `data/barthelme/predictions.zip`, and
> `.venv\Scripts\python.exe -m pytest -q` → **9 passed, 1 skipped**.
> Where a section *designs* a contract that no code implements yet, it says so
> and marks each invented choice as a recommended default to freeze (§6).

---

## 1. DB verdict (db-verify, exact numbers) + seed defects

### 1.0 Verdict

The local DB exists, is internally consistent, and faithfully reproduces its
two sources — but it makes **0 zones rankable in any country**, including both
demo countries. It is a crater/zone seed, not a scoring seed.

| Fact | Exact value (observed) |
|---|---|
| DB file | `data/clearfield.db`, 825,741,312 B, page_count 201,597 × 4,096 B, freelist 4, `user_version=0` |
| `PRAGMA integrity_check` / `foreign_key_check` | `ok` / empty |
| `zones` | **106** = cambodia 25, laos 18, vietnam 63 (exactly GADM feature counts 25/18/63) |
| `craters` | **541,397**, all `source='barthelme_predictions'` = vietnam 511,541, laos 24,197, cambodia 5,659 |
| `finds` | **0** |
| Source `predictions.zip` features | 541,398 (quang_tri 442,157 + tri_border_area 99,241) → seeded 541,397, **exactly 1 skipped**, in tri_border_area (quang_tri seeded 442,157/442,157 incl. 9 assigned to laos; tri_border seeded 99,240 = VN 69,393 + LA 24,188 + KH 5,659) |
| `zones.strike_density` NULL | **106/106** |
| `zones.exposure` NULL | **106/106** |
| `zones.crater_evidence` | non-NULL **12/106** (cambodia 2/25, laos 5/18, vietnam 5/63); NULL 94; exactly 0.0 in 3; range 0.0–95.83839694603431 |
| `zones.priority_score` / `priority_rank` / `scored_at` NULL | **106/106 each** |
| `zones.surveyed_status` | `unsurveyed` 106/106 |
| `zones.geom` / `admin_name` NULL | 0 / 0; all 106 geoms GeoJSON `MultiPolygon`; geom text 2,027–112,967 chars (avg 12,952) |
| Covered zones (id, crater_evidence/km²) | VNM.50_1 95.8384, VNM.34_1 6.9030, LAO.1_1 (Attapu) 2.1476, KHM.20_1 0.4650, LAO.4_1 (Champasak) 0.2475, VNM.21_1 0.1794, LAO.17_1 (Xékong) 0.0288, KHM.22_1 0.0151, LAO.12_1 (Savannakhét) 0.00042, LAO.11_1 (Saravan) 0.0, VNM.46_1 0.0, VNM.54_1 0.0 |
| Demo province | laos `demo_area="Xieng Khouang"` (`countries/laos.json:5`) = zone `LAO.18_1`, `admin_name='Xiangkhoang'`, **crater_evidence NULL** |
| `craters.confidence` NULL, `tile_id` NULL | **541,397/541,397 each** |
| `craters.area_m2` | 25.0–1,383.0, integral in 541,397/541,397 rows; `circularity` 0.0995–0.7854; 0 rows area≤0 or circularity outside [0,1] |
| Crater centroid extent (EPSG:4326) | lon 106.3919–108.1890, lat 14.1668–17.0308 (SE Laos / central VN / NE Cambodia only; nothing near Xieng Khouang ≈19.5°N) |
| Indexes present | `zones_country_rank` + 3 PK autoindexes; no spatial index (SQLite mirror, `db/schema.local.sql:2`) |
| Data on disk | `predictions.zip` 47,886,932 B, `tables.zip` 2,516 B, `README.txt` 3,987 B present; Barthelme `data.zip`/`models.zip` NOT downloaded; GADM 3 files (183,636 / 263,580 / 821,030 B); no `data/thor/`, no `data/osm/`, no `data/imagery/`, no `.env` |

Reconciliation that passed: zone count = GADM sum (106); crater count =
source features − 1; all crater `geom`/`centroid` non-NULL GeoJSON
Polygon/Point; source first-points are UTM metres (e.g. `[693035.0,
1883858.0]`), consistent with the EPSG:32648→4326 transform in
`scripts/seed_db.py:41`; transformed centroids land in the expected lon/lat box.

### 1.1 Seed defects — every one found, with required fix and file:line

All in `scripts/seed_db.py` unless noted. "Required fix" = the change that
closes the defect; none of these are fixed by this synthesis (read-only task).

- **S1 — Re-seed destroys zone state and orphans finds.** `:95` deletes all
  zones of the seeded countries, `:97-100` re-inserts only
  `(id,country,admin_name,geom)`: every re-run resets `surveyed_status` to
  `unsurveyed` and NULLs all score components/scores. Nothing in the repo
  sets `PRAGMA foreign_keys=ON`, so `finds.zone_id → zones.id`
  (`db/schema.local.sql:36`) is unenforced and existing finds would be
  silently orphaned. Fix: upsert zones (`INSERT … ON CONFLICT(id) DO UPDATE`
  on geom/admin_name/country only), enable `foreign_keys=ON`, and refuse (or
  explicitly preserve) when `finds` is non-empty.
- **S2 — False zeros for crater_evidence.** `:136-137` coverage =
  convex hull of crater centroids; `:144-147` any zone merely *intersecting*
  a hull gets a density, including **0.0** (observed LAO.11_1, VNM.46_1,
  VNM.54_1). This breaks the file's own invariant "NULL (not 0) elsewhere:
  no coverage must never read as no craters" (`:14-17`): a hull corner-clip
  reads as surveyed-and-empty. Fix: derive coverage from actual KH-9 scene
  footprints (or hull ∩ scene extent), store coverage fraction, and emit a
  value only above a pinned coverage threshold (§6-U7).
- **S3 — Hull built only from seeded centroids.** `:118-124`: centroids are
  appended only after a zone hit, so craters outside seeded countries (and
  invalid polygons, `:114-116`) never enter the hull — coverage is truncated
  at political borders. Fix: build coverage from all source features of the
  study area before country assignment (or from scene footprints, S2).
- **S4 — Density denominator is full zone area.** `:145`
  `counts/area_km2` uses the whole zone (`:70` geodesic area) even when KH-9
  covered a sliver; documented as "lower bound" (`:14-16`) but no coverage
  fraction is stored, so consumers cannot tell 95%-covered from 1%-covered.
  Fix: denominator = covered area; keep raw count + coverage fraction
  available (new column or documented recompute from `craters`).
- **S5 — Skips are unauditable.** One counter `skipped` is incremented for
  both invalid polygon (`:115`) and outside-all-zones (`:120`) and printed
  as one number (`:149`). Observed: exactly 1 skip in tri_border_area,
  cause unknowable from DB or logs. Fix: separate counters
  (invalid / outside / empty-ring) + print up to N example source indices.
- **S6 — Interior rings dropped, geometry type assumed.** `:112-113`
  `Polygon(feat["geometry"]["coordinates"][0])` keeps only the exterior
  ring and assumes `Polygon`; a `MultiPolygon` or holed crater would be
  mangled or crash. Fix: `shape(feat["geometry"])`, `shapely.make_valid`,
  accept Polygon/MultiPolygon explicitly, count repairs.
- **S7 — Feature streaming can silently drop data.** `:45-51` yields only
  lines starting with the exact bytes `{ "type": "Feature"`; any formatting
  change drops features without error, and nothing reconciles
  yielded vs. source counts (541,398). Fix: parse each non-empty line as
  JSON, check `type=="Feature"`, count lines/features/unparsed, fail if
  unparsed > 0.
- **S8 — Boundary/overlap assignment is lossy and arbitrary.** `:118`
  `predicate="within"` excludes centroids exactly on a zone boundary
  (counted as "outside"); `:122` `zones[hits[0]]` picks an arbitrary zone
  on overlap. Fix: `covers` predicate; deterministic tie-break (largest
  crater-polygon overlap, then smallest zone id); count multi-hit cases.
- **S9 — Crater class discarded; two columns structurally NULL.** Source
  `properties.value ∈ {1..5}` (Pattern/Rim/Group/Crescent/Bowl;
  `data/barthelme/README.txt:5-12`) is dropped by design (`:10-11`), and
  `:126-131` writes `confidence=None, tile_id=None` for all 541,397 rows.
  The morphology class is exactly what the demo's dud-field layer needs
  (`docs/demo-script.md:23`). Fix: add `crater_class INTEGER` to BOTH
  schemas (keeping `db/schema.sql:3` name-parity) and populate it; either
  populate `tile_id` from study area or document it SAM-only.
- **S10 — Partial-download re-run corrupts by omission.** `:56-61` silently
  skips a country whose GADM file is absent, but `:96` deletes ALL
  `barthelme_predictions` craters and `:95` deletes zones only for loaded
  countries: re-running with e.g. VNM GADM missing leaves stale VN zones
  with their craters deleted and crater_evidence frozen. Because
  `list_countries()` (`backend/app/profiles.py:20-21`) includes vietnam,
  seeding only the demo-scope downloads would also silently skip 511,541
  VN craters as "outside". Fix: fail hard if any profile GADM file is
  missing, or scope both DELETEs to the same country set.
- **S11 — CRS is hardcoded and partly wrong at the edge.** `:41` forces
  EPSG:32648 (UTM 48N, valid 102°E–108°E) for both study areas, yet seeded
  centroids reach lon 108.1890°E (UTM 49N); `area_m2`/`circularity`
  (`:125,130`) for those craters carry 48N distortion. Source GeoJSON has
  no `crs` member to check against. Fix: pin CRS per study area from the
  Barthelme metadata, assert raw-coordinate ranges before transform, and
  recompute area/circularity geodesically or in the correct zone.
- **S12 — Zone geometry type not normalized (latent).** `:64-69,98-99`
  stores `shape(...)` as-is. Today all 106 GADM features are MultiPolygon
  (verified), but a future GADM `Polygon` would violate
  `GEOMETRY(MultiPolygon,4326)` (`db/schema.sql:15`) on the PostGIS swap.
  Fix: wrap Polygon→MultiPolygon and assert type + validity + lon/lat range.
- **S13 — Positional crater INSERT.** `:134,140`
  `INSERT INTO craters VALUES (?,?,?,?,?,?,?,?,?)` depends on column order
  in `db/schema.local.sql:21-31`; any schema reorder silently mis-maps
  values. Fix: name the columns.
- **S14 — Circularity cap hides numeric error.** `:130` `min(circ,1.0)`
  silently clamps; observed max 0.7854 so it never fired, but a future >1
  would be invisible. Fix: assert `0 < circ ≤ 1+ε`, count violations.
- **S15 — No verification, versioning, or cleanup at end of seed.** No
  `integrity_check`, count reconciliation, `ANALYZE`, `PRAGMA
  user_version`, or `conn.close()` (`:148-153` commits and prints only).
  DB carries no provenance (which zip MD5 / when / code version). Fix: §1b
  gates + write a `seed_meta` row (or `user_version`) inside the same run.
- **S16 — pip fallback cannot run the seed.** `backend/requirements.txt:3-4`
  lists only fastapi/uvicorn, "keep in sync with pyproject" (`:2`), but
  `pyproject.toml:12-13` also pins `pyproj`/`shapely` which the seed imports
  (`scripts/seed_db.py:31-34`). Fix: either add both to requirements.txt or
  scope the file explicitly to the API only and drop the sync claim.

### 1b. Seed gates (must all pass or the seed exits non-zero)

Pre-flight (before any DELETE — note current code already checks
`predictions.zip` presence before deleting, `scripts/seed_db.py:88-96`;
keep that ordering):

- [ ] G1 Every country profile from `list_countries()` has its GADM file;
  absent file = hard failure, never skip (fixes S10).
- [ ] G2 `predictions.zip` MD5 equals `c79cd869f7d5bb7bfc0e976c0ff7c783`
  (`docs/data-manifest.md:14`, `scripts/download_data.py:23`); GADM sizes
  equal 183,636 / 263,580 / 821,030 B (GADM publishes no MD5,
  `scripts/download_data.py:26-30`).
- [ ] G3 `PRAGMA foreign_keys=ON`; if `finds` is non-empty, zone upsert
  mode only (fixes S1).

Post-seed (inside the same process, before declaring success; values in
brackets are today's observed numbers and must be recomputed per run,
not hard-coded):

- [ ] G4 Reconciliation: source features per study area =
  seeded + invalid + outside, three separate counters printed
  [541,398 = 541,397 + 1 split unknown today] (fixes S5, S7).
- [ ] G5 `zones` count per country = GADM feature count per country
  [25/18/63 → 106]; zero NULL `geom`/`admin_name`; every geom valid
  MultiPolygon with lon ∈ [-180,180], lat ∈ [-90,90] (fixes S12).
- [ ] G6 Every crater: `area_m2 > 0`, `0 ≤ circularity ≤ 1`, centroid
  within its assigned zone's country bbox, id unique, `geom`/`centroid`
  parse as Polygon/Point (fixes S6, S8, S14).
- [ ] G7 `crater_evidence` non-NULL exactly for covered zones; no covered
  zone gets 0.0 unless its covered area was actually imaged and empty
  (fixes S2–S4); recompute one covered zone's density by an independent
  SQL count and compare [today: 12 covered, 3 false-zero suspects].
- [ ] G8 `PRAGMA integrity_check` = `ok`; `PRAGMA foreign_key_check`
  empty; orphan-finds count = 0.
- [ ] G9 Provenance stamped: source MD5s, UTC timestamp, per-area
  counters, code version (fixes S15).
- [ ] G10 A second consecutive seed run produces byte-identical
  table contents (idempotence diff on ordered dumps), and does not
  change `surveyed_status` or any `finds` row (fixes S1).

---

## 2. Scoring contract (exact)

Current state: `pipelines/scoring.py:17-20` is a keyword-only stub that
always raises `NotImplementedError`; `tests/test_scoring.py:6-9` pins
that behaviour; the CLI (`:23-24`) exits via
`pipelines/_profile.py:19-23`. The formula in prose is "THOR strike
density × crater evidence × exposure, minus already-surveyed status"
(`docs/architecture.md:22`, `pipelines/scoring.py:3-6`,
`countries/README.md:23-25`) — operator, scales, and None rules are
written nowhere. The contract below is the one to implement; items
marked ★ are unpinned choices frozen here as recommended defaults (§6).

### 2.1 Inputs

- Pure function keeps today's signature:
  `score_zone(*, strike_density, crater_evidence, exposure, surveyed_status)`
  (`pipelines/scoring.py:17`). No DB, no I/O, no randomness, no clock.
- ★ The three numeric inputs to `score_zone` are **already normalized
  to [0,1]** by the runner (§2.2). Raw stored components stay on the
  zone row untouched — scoring never overwrites a component
  (`db/schema.sql:16-26` invariant).
- `surveyed_status ∈ {unsurveyed, surveyed, cleared}` (CHECK constraint,
  `db/schema.local.sql:14-15`).

### 2.2 Normalization (runner-side, per country)

Raw components are incommensurable (observed crater_evidence alone
spans 0.00042–95.84/km²), so a raw product is meaningless. ★ Runner
computes, per country and per component, over zones where that
component is NOT NULL:

```
n(x) = log1p(x) / log1p(max_country)   if max_country > 0
n(x) = 0.0                              if max_country == 0
```

- Rationale to record in code: `log1p` tames the 5-decade spread;
  dividing by the country max makes "highest in country = 1.0"
  citable by Spark; all-equal positive inputs map to 1.0 for every
  zone (component does not discriminate, stays neutral in a product).
- Normalization stats are computed from stored components only, in
  the same run, and are identical for identical DB contents.

### 2.3 Formula, surveyed handling, validation

```
factor = {unsurveyed: 1.0, surveyed: 0.25, cleared: 0.0}        ★ values
score  = n_strike * n_crater * n_exposure * factor[surveyed_status]
```

- "Minus surveyed status" is implemented as this multiplicative factor
  (a literal subtraction is undefined against a [0,1] product; §7-C6).
- Validation inside `score_zone`: any numeric input that is not None
  must be a finite real with `0.0 ≤ x ≤ 1.0`, else `ValueError`;
  unknown `surveyed_status` → `ValueError`. NaN/inf → `ValueError`
  (never a silent 0).
- Output: `float` in [0,1], or `None` (§2.4). Nothing else.

### 2.4 None semantics

- **Any** of the three components `None` → return `None`
  (unscorable). There is no partial scoring and no imputing 0 —
  the same NULL≠0 rule the seed enforces for coverage
  (`scripts/seed_db.py:14-17`).
- Consequence on today's DB (state it, don't soften it): with
  strike_density and exposure NULL for 106/106 zones, a correct
  scoring run today scores **0 zones in every country** and that is
  the expected output while those components are NULL (§5; status updated 2026-10-28 there).

### 2.5 Ranks, tie-break, 0-scored output

- Ranks are per country, assigned by the runner over scorable zones
  only: unique ordinal 1..N (`priority_rank INTEGER`,
  `db/schema.sql:25`; demos cite "#3", so shared ranks are not allowed). ★
- ★ Tie-break, in order: score DESC → raw `strike_density` DESC →
  raw `crater_evidence` DESC → raw `exposure` DESC → `zones.id` ASC.
- 0-scored output: a computed 0.0 (some normalized component is 0, or
  status `cleared`) is a **real score** — the zone is ranked after all
  positive scores under the same tie-break. Only `None`-score zones
  get `priority_score = NULL, priority_rank = NULL`.

### 2.6 Runner writes (the only writer)

- CLI stays `python pipelines/scoring.py --country <id>` via
  `pipelines/_profile.py:12-16`; unknown country fails through
  `load_country` before any write.
- Writes exactly three columns — `priority_score`, `priority_rank`,
  `scored_at` — per `db/schema.sql:22-26` ("Nothing else may write
  these two columns" extends to `scored_at`). Models never write them
  (`pipelines/scoring.py:6`).
- One transaction per country: every zone of the country is rewritten
  (scorable → score+rank; unscorable → NULL+NULL), `scored_at` = one
  UTC timestamp for the whole run (ISO-8601 text in SQLite,
  `db/schema.local.sql:18`). Rerunning on unchanged components
  changes only `scored_at`.
- Runner prints per country: zones total, scored, unscored
  (with the NULL-component breakdown), so a 0-scored country run is
  visibly 0, never a silent success.
- DB target: `backend/app/config.py:12` `LOCAL_DB_PATH` (env
  `CLEARFIELD_LOCAL_DB`, default `data/clearfield.db`) until the
  PostGIS swap; same accessor as the API (§3.4).

### 2b. Scoring test list

Replace the stub-pinning test; keep direct function calls (no
TestClient needed). Minimum set, each independently falsifiable:

- [ ] T-S1 Determinism: same inputs → identical float, 100 repeats
  (un-skips the intent at `tests/test_scoring.py:12-16`).
- [ ] T-S2 Exact product: (1,1,1,unsurveyed)=1.0; (0.5,0.5,0.5)=0.125.
- [ ] T-S3 Surveyed factor: surveyed = 0.25× unsurveyed at equal
  components; cleared = 0.0 at maximal components.
- [ ] T-S4 None propagation: each single-None and all-None → None
  (never 0.0, never exception).
- [ ] T-S5 Validation: -0.1, 1.1, NaN, inf, non-numeric → ValueError;
  `surveyed_status="bogus"` → ValueError.
- [ ] T-S6 Normalization: hand-computed `log1p` ratios on a 3-zone
  fixture; country-max zone → 1.0; all-zero component → all 0.0;
  all-equal positive → all 1.0; NULL component excluded from stats.
- [ ] T-S7 Runner on `tmp_path` DB (pattern of
  `tests/test_local_schema.py:9-12`): ranks 1..N unique per country;
  tie resolved by raw strike then id; countries do not interleave.
- [ ] T-S8 Runner None handling: zone with one NULL component keeps
  NULL score+rank but gets `scored_at`; 0.0-score zone is ranked last.
- [ ] T-S9 Runner idempotence: second run changes only `scored_at`;
  component columns byte-identical after scoring.
- [ ] T-S10 Today's-DB shape (fixture mimicking §1: all
  strike/exposure NULL): run scores 0 zones, exits 0, prints 0 —
  proving no faked ranking before THOR/OSM.
- [ ] T-S11 `tests/test_scoring.py:6-9` stub test is deleted in the
  same change that implements scoring (it would otherwise invert).

---

## 3. API contract — `GET /zones` and `POST /finds` (exact)

Current state: `backend/app/main.py:42-47` `zones(country="laos")`
unconditionally 501s; `:60-65` `finds()` takes no input and 501s.
Only `/health`, `/countries`, `/countries/{id}` are real (`:17-39`).
`tests/test_api.py:29-34` pins the three 501s. Contract below replaces
the two named stubs; `/explain` is out of scope here (blocked, §5).
★ = recommended default for an unpinned choice (§6).

### 3.1 `GET /zones`

Query params:

| Param | Type | Default | Rule |
|---|---|---|---|
| `country` | str | `"laos"` (keep `main.py:43`) | Must resolve via `load_country` (`backend/app/profiles.py:24-34`); unknown → **404** `unknown country: <id>`, same shape as `main.py:38-39` |
| `surveyed_status` | enum? | ★ none (all) | One of `unsurveyed|surveyed|cleared`; invalid → **422** (FastAPI validation) |
| `include_unscored` | bool | ★ `true` | `false` drops `priority_rank IS NULL` rows |
| `limit` | int | ★ 100, range 1–500 | Out of range → 422 |
| `offset` | int | ★ 0, ≥0 | Negative → 422 |

Response 200 (envelope ★, matching the current `-> dict` annotation):

```json
{
  "country": "laos",
  "count": 18,              // rows in this page
  "total": 18,              // ★ rows matching filters before limit/offset
  "zones": [
    {"id": "LAO.1_1", "country": "laos", "admin_name": "Attapu",
     "geom": {"type": "MultiPolygon", "coordinates": []},
     "strike_density": null, "crater_evidence": 2.14758095762636,
     "exposure": null, "surveyed_status": "unsurveyed",
     "priority_score": null, "priority_rank": null, "scored_at": null}
  ]
}
```

- Fields = exactly the `zones` columns (`db/schema.local.sql:6-19`).
  NULLs serialize as JSON `null` — never dropped, never 0. Components
  are always present so Spark can cite them (`db/schema.sql:5-7`;
  template `agent/templates/en/survey-report.md:3-7` needs all six).
- ★ `geom` is the stored GeoJSON text **parsed back to an object**
  (a quoted string forces double-decoding on every client).
- Ordering: `ORDER BY (priority_rank IS NULL), priority_rank ASC,
  id ASC` — ranked zones first in rank order, unscored zones last by
  id; identical `limit/offset` pages are stable across calls.
- On today's DB this returns real rows with null scores (laos 18,
  cambodia 25, vietnam 63), `crater_evidence` non-null only for the
  12 covered zones of §1. That is the honest pre-scoring output.

### 3.2 `POST /finds`

Accepts **one already-structured find record** (what field triage
will eventually produce; the endpoint does not wait for Glimmer —
§7-C7). Request JSON (pydantic model; unknown fields → 422 ★):

| Field | Required | Rule |
|---|---|---|
| `id` | ★ yes, client-generated | Stable offline id (retry key). Duplicate-id replay: ★ if the stored row is field-identical → **200** with stored record; if same id different content → **409** |
| `country` | yes | Must resolve via `load_country`, else 404 as §3.1 |
| `zone_id` | no, default null | If given, must exist in `zones` for that country, else **422**. ★ Server does NOT derive zone from location in v1 (no spatial index in SQLite mirror) |
| `object_type`, `condition`, `estimated_size`, `notes`, `photo_ref` | no | Free text, stored verbatim (`db/schema.local.sql:37-44`) |
| `risk_flag` | no, default `unknown` | Enum `unknown|suspect_live|inert|escalated` (`db/schema.local.sql:40-41`); invalid → 422, never reach the CHECK as a 500 |
| `location` | no | ★ GeoJSON Point `{"type":"Point","coordinates":[lon,lat]}` (matches stored form); lon∈[-180,180], lat∈[-90,90] else 422 |
| `recorded_at` | no | Client timestamp stored verbatim (offline capture time) |
| `synced_at` | — | **Server-set** to UTC now; any client value is rejected/ignored ★ (reject: unknown-field rule) |

- Success: **201** with the stored record (all `finds` columns,
  `db/schema.local.sql:33-47`, `location` parsed as in §3.1).
- Safety: the endpoint stores and echoes only. No response field may
  instruct approaching a suspect item (`field/triage.py:5-6`,
  `docs/architecture.md:46`); `risk_flag` is data, not advice.
- No scoring side effects: inserting a find does NOT re-rank zones.
  Re-scoring is the explicit runner of §2.6 (demo Moment 3's "score
  updates" step, `docs/demo-script.md:19`, must call it explicitly).

### 3.3 Error semantics (shared)

- 404 unknown country (both endpoints) — `HTTPException` detail
  string, existing style (`main.py:39`).
- 422 for every validation failure above (pydantic/FastAPI default
  body). Handlers must validate enums/ranges *before* touching the
  DB so SQLite `IntegrityError`/CHECK failures never surface as 500.
- ★ DB file missing / tables missing → **503** with detail naming
  `CLEARFIELD_LOCAL_DB` and the seed command. (501 stays reserved
  for not-implemented features, the repo's existing honesty pattern
  at `main.py:44-57,62-65`.)
- `/explain` keeps its current 501 behaviour unchanged (`main.py:50-57`).

### 3.4 DB accessor + test design

- New module ★ `backend/app/db.py`: `get_conn(db_path=None, *,
  readonly: bool)` → `sqlite3.Connection` with `row_factory=Row`,
  `PRAGMA foreign_keys=ON`, URI `mode=ro` for reads. Path resolves
  from `backend/app/config.py:12` (`LOCAL_DB_PATH`), overridable per
  call. `/zones` uses readonly; `/finds` uses a write connection
  with an explicit transaction; scorer (§2.6) shares this accessor.
- Handlers keep direct-call testability: `zones(country=...,
  db_path=None)` / `create_find(payload, db_path=None)` with the
  FastAPI route as a thin wrapper — because tests in this repo call
  handlers directly (sandbox blocks TestClient sockets,
  `tests/test_api.py:3-6`). Do not introduce TestClient-only paths.
- Note for implementers on this machine: aggregate queries over the
  541k-row craters table needed `PRAGMA temp_store=MEMORY` under the
  sandboxed shell during this verification (`unable to open database
  file` on temp spill). `/zones`/`/finds` queries don't scan
  `craters`; any future craters aggregate must set it.

### 3b. API test list

Fixture: `tmp_path` DB from `db/schema.local.sql` (pattern
`tests/test_local_schema.py:9-12`) with 2 countries × few zones
(mixed ranked/unscored/statuses); handlers called directly.

- [ ] T-A1 `/zones` happy path: envelope fields, `total` vs page
  `count`, all 11 zone fields present, `geom` is an object.
- [ ] T-A2 Ordering: ranked ascending, unscored last by id; two pages
  via limit/offset are disjoint and concatenate to the full order.
- [ ] T-A3 Filters: `surveyed_status`, `include_unscored=false`.
- [ ] T-A4 Null fidelity: NULL components/scores appear as `None`,
  never 0/missing (use NULL-heavy fixture rows like today's DB).
- [ ] T-A5 Errors: unknown country → 404; bad status/limit/offset →
  422; missing DB file → 503 (not 500, not 501).
- [ ] T-A6 `POST /finds` 201 round-trip: stored row equals response;
  `synced_at` server-set; defaults (`risk_flag=unknown`,
  `zone_id=None`) applied.
- [ ] T-A7 Finds validation: bad risk_flag, bad location ranges/type,
  nonexistent zone_id, unknown country, unknown extra field,
  client `synced_at` → 422/404 as §3.2–3.3; no partial row written.
- [ ] T-A8 Finds replay: identical re-POST → 200 same record, still
  one row; same id different content → 409, original unchanged.
- [ ] T-A9 Isolation: `/finds` insert does not change any zone's
  score/rank; `/zones` never writes (readonly connection proves it).
- [ ] T-A10 Update `tests/test_api.py:29-34`: `zones`/`finds` leave
  the 501 tuple, `explain` stays 501 (both META-key branches).
- [ ] T-A11 Real-DB smoke (marked/optional, read-only): against
  `data/clearfield.db`, laos returns 18 zones, exactly 5 with
  non-null `crater_evidence`, ranks all null — pins §1 numbers.

---

## 4. Doc fixes — every one, file:line, replacement fact (re-based on §1)

Winner in every row: code + DB as verified in §1. "Replacement" is the
fact the text must state, not full prose.

| # | Location | Wrong/stale claim | Replacement fact |
|---|---|---|---|
| D1 | `README.md:5` | "no data, scoring, or live model calls yet" | Data IS downloaded+seeded: 106 zones, 541,397 craters, 825,741,312 B DB; scoring + live model calls still absent; 0 zones rankable (strike/exposure NULL ×106) |
| D2 | `README.md:48-50` | download/seed "Not yet implemented… prints the plan" | Both implemented: `scripts/download_data.py` (Barthelme 5 + GADM 3 pinned), `scripts/seed_db.py` (GADM zones + Barthelme craters → SQLite). THOR/OSM still manual/unpinned |
| D3 | `README.md:9,13` + `docs/demo-script.md:11-15` | Ranked Laos/Cambodia maps, "why #3" demo | No ranking exists anywhere; crater coverage reaches only lat 14.17–17.03; demo province LAO.18_1 (Xieng Khouang) has crater_evidence NULL; Cambodia covered 2/25 zones, Laos 5/18. Demo Moments 1–2 blocked until §5 lands (or demo province moves into covered area, §6-U10) |
| D4 | `README.md:55`, `data/README.md:3-5` | "nothing under data/ is committed… every file MD5-checked" | Gitignore does exclude `data/*` except README/.gitkeep (`.gitignore:11-13`) — keep. But MD5: GADM files have NO source checksum (`scripts/download_data.py:26-30`); only the 5 Barthelme files are MD5-verified, and only 3 of them are downloaded |
| D5 | `docs/getting-started.md:5` | "sections 2,3,5 stubs… no data downloaded, no DB seeded" | §2/§3-local work today (download+seed as D2); §5 pipelines still stubs; DB seeded with §1 contents |
| D6 | `docs/getting-started.md:29` | download pulls Barthelme+UXOTi+AMLID+GADM+OSM | Pulls Barthelme + GADM only; UXOTi_NPA/AMLID/OSM unpinned TODO (`scripts/download_data.py:86`); present locally: predictions+tables+README (no `data.zip`/`models.zip`) |
| D7 | `docs/getting-started.md:37-41` | `createdb`/`psql`, seed "loads GADM, OSM, THOR, crater data" | Seed is SQLite-only, loads GADM + Barthelme craters only; PostGIS path does not exist yet (`DATABASE_URL` read at `backend/app/config.py:11`, used nowhere except health flag) |
| D8 | `docs/getting-started.md:12` | "~8 GB free… Barthelme unpacks ~4 GB" | Local footprint today ≈874 MB (DB 825.7 MB + zip 47.9 MB); 8 GB applies only if `data.zip` (1.85 GB) + `models.zip` (0.97 GB) + THOR (~1.5 GB) are also fetched |
| D9 | `docs/data-manifest.md:14` | "500K+ craters" | Exact: 541,398 source features (442,157 quang_tri + 99,241 tri_border_area); 541,397 seeded, 1 skipped (cause unrecorded, S5) |
| D10 | `docs/data-manifest.md:40` | "Boundaries — GADM administrative units" (unpinned) | Pin: GADM 4.1 admin-1 `gadm41_{LAO,KHM,VNM}_1.json`, 183,636/263,580/821,030 B, no source MD5, 18/25/63 features (also closes the `_todo` at `countries/laos.json:18` for GADM half) |
| D11 | `docs/data-manifest.md:31` + `README.md:9` | THOR mission counts (Laos 1,041,519; Cambodia 144,944…) | Unverified locally (no THOR file; manual-gated). Mark as source-claimed, not repo-verified. Note VN profile must map South+North Vietnam rows (`countries/vietnam.json:18`) before "Vietnam" totals mean anything (581,897+1,620,422) |
| D12 | `frontend/index.html:5-6`, `frontend/README.md:3-5` | "lands with seeded zone data… No zones exist yet" | Zones ARE seeded (106) but unscored; the blocker is `/zones` 501 + §2 scoring, not missing zone data |
| D13 | `.env.example:7` | local DB "created by seed_db once it lands" | seed_db has landed; this is the live scaffold DB (826 MB) |
| D14 | `backend/app/main.py:3-6` (docstring) | zones "needs seeded data + scoring" | Seeded data exists; zones need the §3 implementation (+ §2 to be ranked). Finds detail (`:64`) "needs field triage" — see §7-C7 winner |
| D15 | `docs/architecture.md:19,22` | SAM/PostGIS pipeline described in present tense; F1 0.61 | Present-tense parts are target state: no SAM run, no PostGIS, everything runs on the SQLite mirror; F1 0.61 is the Barthelme paper claim — `tables.zip` (2,516 B) is downloaded but was not re-verified in this pass, mark unverified |
| D16 | `countries/README.md:23-25` | "the formula is fixed (… minus surveyed status)" | Formula prose only; normalization/None/tie rules undefined until §2 of this file is frozen; surveyed data source does not exist (106/106 `unsurveyed` by default, nothing writes `surveyed`) |
| D17 | `scripts/seed_db.py:3-7` (docstring) | Accurate, keep — but complete it | Add: vietnam is seeded (63 zones / 511,541 craters = 94.5% of craters) despite demo scope Laos+Cambodia, because `list_countries()` drives seeding; add §1 counts after first run |
| D18 | `data/README.md:7-15` | "Expected layout once downloads land" incl. `data/osm/`, `data/imagery/`, `data/thor/` | Update to actual: only `barthelme/` (3 files), `gadm/` (3 files), `clearfield.db` exist; the other three dirs do not |
| D19 | `docs/demo-script.md:19` | triage sync "→ the zone's score updates" | No such automatic path exists or is designed; per §3.2 re-scoring is an explicit runner invocation |

No doc fix is needed for: `agent/README.md` / `demo/cached-responses/README.md`
/ `field/prompts/README.md` (all honestly state stub/empty status,
verified); `tests/` are code, covered by T-S11/T-A10.

---

## 5. Blocked on META_API_KEY / OSM (Vietnam) / crater coverage (status updated 2026-10-28)

> **Update 2026-10-28 (the audit text below is the Oct 27 snapshot):**
> OSM exposure **has landed** for Laos + Cambodia (`zones.exposure`
> non-NULL 43/106; Vietnam 0/63, no extract acquired) and the Cambodia
> demo is set (Tbong Khmum, `KHM.25_1`). THOR is **RESOLVED**: the
> corrected seed ran 2026-10-28 (`scripts/seed_thor.py`,
> `docs/thor/thor_final_spec.md` §9: forced EPSG:1542 datum transform,
> SACCOACT dedup from 1971-04-01, weapon filter not applied; D1–D4
> confirmed as pinned defaults, §9.6) — C summary: rows 4,670,422,
> assigned 3,401,836 (cambodia 191,184 / laos 1,090,845 / vietnam
> 2,119,807), invalid 1,130,146, outside 108,385, deduped_saccoact
> 30,055, corrected mismatch 144,468. `strike_density` is non-NULL
> 106/106 and scoring ranks 6 zones: Laos 4/18, Cambodia 2/25,
> Vietnam 0/63. The remaining blockers are crater coverage (only
> 4 Laos + 2 Cambodia + 3 Vietnam zones have `crater_evidence`, and
> both demo provinces, Xiangkhoang `LAO.18_1` and Tbong Khmum
> `KHM.25_1`, are among the NULL ones) and Vietnam exposure.
> `survey-report.md:4` `strike_density` is now fillable for every zone.

**META_API_KEY** (absent: no `.env` file exists; `backend/app/config.py:10`
reads env only):

- `POST /explain` — 501 by design (`backend/app/main.py:50-57`), two
  distinct details (key missing vs. agent unwired). Stays blocked even
  with a key until Spark wiring exists.
- `agent/spark.py:6-9` `explain_zone` — raises without key, stub with key.
  Consequences: demo Moment 2 explanations/reports, `agent/templates/`
  rendering (only `en/survey-report.md` exists; `km/`, `lo/` are empty
  `.gitkeep` dirs), cached demo responses cannot be generated (and must
  not be hand-written, `demo/cached-responses/README.md:12-13`).
- `pipelines/sam_segment.py:15-16` — needs key AND `pipelines/tiling.py`
  output; tiling itself (`:10-11`) needs `data/imagery/` (absent).
  Consequence: no SAM crater source; `craters.source='sam31'`
  (`db/schema.sql:32`) has 0 rows; Barthelme is the only crater evidence.
- NOT key-blocked: Glimmer field triage (`field/triage.py:10-13`) is a
  local llama.cpp path, blocked on laptop benchmarking
  (`field/prompts/README.md:3-4`), not on the Meta key. `/zones`,
  `/finds`, and §2 scoring need no key at all.

**THOR** (historical Oct-27 snapshot — superseded by the 2026-10-28 update above, where THOR is RESOLVED; Oct 27: CSV then recorded absent under its old name; manual data.world account,
`scripts/download_data.py:85`, `docs/getting-started.md:32`):

- `zones.strike_density` NULL 106/106 → by §2.4, **0 zones scorable**,
  demo Moments 1–2 impossible, `survey-report.md:4` unfillable.
- Cambodia `demo_area` stays null (`countries/cambodia.json:5,16`;
  pinned by `tests/test_profiles.py:15-18`).
- THOR `country_filter` values (`LAOS`/`CAMBODIA`/`VIETNAM`,
  `countries/*.json:9`) are guesses until the CSV header is seen
  (`countries/laos.json:17`); Vietnam needs a South+North mapping
  (`countries/vietnam.json:9,18`) that the single-string filter cannot
  express yet.

**OSM** (no extract downloaded, URL/checksum unpinned,
`scripts/download_data.py:86`; profiles carry only an extract name,
`countries/laos.json:13` etc.):

- `zones.exposure` NULL 106/106 → independently sufficient to keep
  scorable-zone count at 0 even if THOR landed tomorrow.
- "Proximity to villages/farmland/schools/roads" (`README.md:13`) has
  no defined computation anywhere in the repo (§6-U9) — data alone
  does not unblock exposure; a formula must be pinned too.

Also absent but NOT blocking the above: PostGIS (`DATABASE_URL` unset;
SQLite mirror is the runtime), UXOTi_NPA/AMLID packs, Barthelme
`data.zip`/`models.zip`, Sentinel-2/NICFI/KH-9 raw imagery.

---

## 6. Unresolved / unpinned choices (each with recommended default ★)

- **U1 Normalization** (nothing in repo): ★ per-country
  `log1p(x)/log1p(max)` runner-side (§2.2). Alternatives rejected:
  raw product (scale-dominated), global max (breaks per-country
  ranking), percentile ranks (less citable).
- **U2 Surveyed factor values**: ★ 1.0 / 0.25 / 0.0 (§2.3). Also
  unresolved upstream: *nothing* ever writes `surveyed`/`cleared`
  (no source; IMSMA gated, `README.md:36`). ★ Until a stats source
  lands, surveyed handling is code-correct but data-inert — say so.
- **U3 Partial-component scoring**: ★ forbidden; None → None (§2.4).
- **U4 Rank uniqueness**: ★ unique ordinal 1..N per country with the
  §2.5 tie-break (demo cites "#3").
- **U5 `cleared` zones ranked or excluded**: ★ ranked with score 0.0
  (§2.5) so `/zones` ordering stays total; UIs may filter.
- **U6 Scoring weights per country**: profiles deliberately have
  none (`countries/README.md:23-25`). ★ Equal weights (plain
  product) globally until real THOR/OSM data argues otherwise.
- **U7 Crater coverage definition** replacing the convex hull (S2):
  ★ KH-9 scene footprints from Barthelme metadata; emit density
  only when covered fraction ≥ 0.5 of the zone, denominator =
  covered area, store coverage fraction. Threshold value itself
  needs an owner decision when footprints are in hand.
- **U8 Crater class persistence** (S9): ★ add `crater_class INTEGER`
  (1–5) to both schemas + backfill on next seed. If rejected,
  delete demo Moment 4's morphology claim instead.
- **U9 Exposure formula**: ★ (to pin before any OSM seed code)
  per-zone: population-proximity score = normalized sum over
  OSM villages/schools within zone + farmland share + road density,
  each stored… — but schema has ONE `exposure` column. ★ Compute
  one documented scalar, keep the per-feature inputs in the seed
  script's printed provenance, revisit only if Spark needs the split.
- **U10 Demo province vs. coverage**: Xieng Khouang is uncovered by
  Barthelme (§1). Options: (a) move Laos demo to a covered province
  (Attapu, highest LA crater_evidence 2.1476/km²), (b) wait for
  SAM over Xieng Khouang imagery (needs META key + tiling). ★ (a)
  for the hackathon demo; keep `demo_area` change explicit in the
  profile + `tests/test_profiles.py:16`.
- **U11 Cambodia demo province**: blocked on THOR (§5). From crater
  coverage alone only KHM.20_1/KHM.22_1 have any evidence. ★ Pick
  from THOR strike density intersected with whatever crater source
  covers it; do not pick from Barthelme coverage alone.
- **U12 `/zones` envelope + geom encoding + pagination**: ★ §3.1
  (`{country,count,total,zones[]}`, geom as object, limit 100/500).
- **U13 `/finds` identity + replay**: ★ client-generated `id`
  required, identical replay → 200, conflict → 409 (§3.2). Batch
  sync (list payload) deferred; single-record first.
- **U14 `/finds` zone derivation**: ★ none in v1 (client may send
  `zone_id`); server-side point-in-polygon waits for PostGIS.
- **U15 Missing-DB status code**: ★ 503 (§3.3).
- **U16 Vietnam seed scope**: seeded today only because a profile
  exists (S10/D17). ★ Keep (Barthelme validation needs Quang Tri),
  but make the seed's country set explicit in output and docs.
- **U17 Strike density unit**: missions/km² vs ordnance-weight/km²
  undefined. ★ missions (sorties with coordinates) per km² first —
  it's the count the manifest already cites (D11); record the unit
  string wherever the component is displayed.
- **U18 DB accessor module/name**: ★ `backend/app/db.py:get_conn`
  (§3.4), shared by API + scorer; no ORM.

## 7. Cross-report contradictions (winner named)

- **C1 Prior workflow results**: caller says read 6 priors "IN FULL";
  handoff says all 6 belong to another parent (gap, no reads).
  **Winner: the gap markers** — this file is a first-hand rebuild,
  and any number below that a prior report stated differently has
  been re-derived, not merged.
- **C2 "No data / no seed"** (`README.md:5`,
  `docs/getting-started.md:5`, `frontend/index.html:6`) vs. 826 MB
  DB + implemented seed/download. **Winner: DB + code** (D1, D2, D12).
- **C3 Seed contents**: getting-started "loads GADM, OSM, THOR"
  (`:40`) vs. `scripts/seed_db.py:3-17` (GADM + Barthelme only,
  THOR/OSM explicitly NULL). **Winner: seed code + DB null counts.**
- **C4 Canonical DB**: `db/schema.sql` PostGIS "canonical" vs. all
  runtime code paths use SQLite (`backend/app/config.py:12`,
  `scripts/seed_db.py:78-79`). **Winner today: SQLite mirror**;
  PostGIS is a target schema only. Name-parity rule
  (`db/schema.sql:3`) still binds both.
- **C5 NULL≠0 invariant** (`scripts/seed_db.py:14-17`) vs. three
  zones stored `crater_evidence=0.0` via hull-intersect (§1, S2).
  **Winner: the invariant** — the 0.0 rows are a seed defect to fix,
  not evidence of empty land.
- **C6 "× … minus surveyed"** (three doc locations, §2) — subtraction
  vs. product ambiguity. **Winner: §2.3 multiplicative factor**
  (only reading defined on a [0,1] product; U2 records the choice).
- **C7 `/finds` blocked on field triage** (`backend/app/main.py:64`)
  vs. schema design "one schema for HQ and field… sync unchanged"
  (`db/schema.sql:41-42`). **Winner: schema design** — §3.2 accepts
  structured records now; Glimmer becomes one producer among others.
- **C8 Demo geography**: Laos demo = Xieng Khouang
  (`countries/laos.json:5`, `docs/demo-script.md:11-15`) vs. crater
  coverage lat ≤17.03 and `LAO.18_1` NULL. **Winner: coverage
  data** (U10). Related: `demo_area` "Xieng Khouang" ≠ GADM
  `admin_name` "Xiangkhoang" — **winner: GID `LAO.18_1`** as the
  join key; name matching is broken by construction.
- **C9 requirements sync**: `backend/requirements.txt:2` "keep in
  sync" vs. missing pyproj/shapely. **Winner: `pyproject.toml`**
  (S16).
- **C10 "Every file MD5-checked"** (`data/README.md:5`,
  `docs/data-manifest.md:3`) vs. GADM `md5=None`
  (`scripts/download_data.py:26-30`). **Winner: download code**
  (D4).
- **C11 Repo status "scaffold… tests are in place"** (`README.md:5`)
  vs. test reality: 9 passed, 1 skipped, and two tests exist only to
  pin stubs (`tests/test_scoring.py:6-9`, `tests/test_api.py:29-34`).
  **Winner: test run** — green suite proves honesty of stubs, not
  presence of features. (Also: `git status` failed in this sandbox,
  exit 128, so committed-vs-working-tree state is **unverified**;
  all claims here are about the working tree as read.)
- **C12 Crater `confidence`**: architecture promises SAM polygons
  "with area, circularity, confidence" (`docs/architecture.md:19`)
  vs. 541,397/541,397 NULL for the only seeded source.
  **Winner: DB** — UI/Spark must not assume confidence exists for
  Barthelme rows (S9).

---

## Implementation order (checklist summary)

1. [ ] Seed fixes S1–S16 + gates G1–G10; re-seed; re-verify §1 numbers.
2. [ ] Doc fixes D1–D19 (cheap; stops the demo being planned on
   nonexistent rankings).
3. [ ] `backend/app/db.py` accessor (§3.4) → `GET /zones` (§3.1) →
   `POST /finds` (§3.2) + tests T-A1…T-A11. (No external blocker.)
4. [ ] Scoring pure function + runner (§2) + tests T-S1…T-S11.
   Lands and passes *before* THOR/OSM — it will correctly score
   0 zones on today's DB (T-S10).
5. [ ] Manual THOR download → strike seed (pin country mapping +
   unit, U17) → Cambodia demo province (U11).
6. [ ] OSM extracts pinned + exposure formula frozen (U9) → exposure
   seed. First non-zero ranking appears here.
7. [ ] META_API_KEY → Spark `/explain` + report templates (km/lo) +
   cached demo responses; SAM path (tiling → sam_segment) only if
   demo scope needs craters beyond Barthelme coverage (U10).



