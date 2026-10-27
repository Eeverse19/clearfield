# THOR `strike_density` — final merged implementation spec (parent-ready)

Sources merged: `.uv-tmp/thor_scan.json` (Task A full scan), `.uv-tmp/thor_seed_spec.md`
(Task B), `.uv-tmp/thor_doc_edits.md` (Task C). Cross-checks run 2026-10-26 via
`.uv-tmp/thor_crosscheck.py`; zones DB queried read-only (`mode=ro`). Where B and C
disagree, this file picks one resolution and marks the superseded text.

## 0. Verified THOR numbers (observed = truth; manifest claims superseded)

- Zip: `~/Downloads/THOR_Vietnam.zip`, 457,332,289 B,
  md5 `3b39a4921f7c0912fbe961184911167e`, Deflate64 (method 9) — stdlib `zipfile` /
  Windows `tar` cannot read it; 7-Zip (`C:\Program Files\7-Zip\7z.exe`) can.
- CSV (already extracted by Task A): `data/thor/THOR_Vietnam_7_31_2013.csv`,
  2,627,971,171 B, md5 `939f28d770d9b3b9acd37553eab0fb85`, 85 cols, BOM on first
  header name (open `encoding="utf-8-sig"`), 6 short rows padded by the scanner.
- Rows: **4,670,422** data rows; `MSNDate` min 19650601, max 19750630, 0 invalid/empty.
- Coord validity (rule in §2.3): **3,540,276 valid**, 1,130,146 invalid (0 `zero_zero`).
  Identity holds exactly: 3,540,276 + 1,130,146 = 4,670,422.
- Zone assignment (point-in-zone over the 106 DB zones): **3,419,286 assigned**,
  120,990 valid-but-outside-all-zones. Per-zone mission counts sum to exactly
  3,419,286 (cambodia-zone 194,809 + laos-zone 1,094,447 + vietnam-zone 2,130,030);
  all 106 zones receive >= 1 mission, so on real data no zone takes the 0.0 branch.
- Per-`TgtCountry` valid-coords vs data.world manifest claims — **all five claims are
  LOW; none match** (`manifest_all_match: false`). Observed values replace them everywhere:

  | TgtCountry | manifest claim | observed valid | delta (obs-claim) | total rows | invalid coords |
  |---|---|---|---|---|---|
  | LAOS | 1,041,519 | 1,087,019 | +45,500 | 1,269,847 | 182,828 |
  | SOUTH VIETNAM | 1,620,422 | 1,658,608 | +38,186 | 2,203,684 | 545,076 |
  | NORTH VIETNAM | 581,897 | 607,482 | +25,585 | 695,662 | 88,180 |
  | CAMBODIA | 144,944 | 147,097 | +2,153 | 223,722 | 76,625 |
  | THAILAND | 2,427 | 2,574 | +147 | 60,593 | 58,019 |

  Other `TgtCountry` values present: `(EMPTY)` 216,780 rows / 37,377 valid,
  `UNKNOWN` 59/45, `WESTPAC WATERS` 74/73, `PHILLIPINES` 1/1. Modern-Vietnam
  valid total (S+N) = 2,266,090. `VIETNAM` as a value occurs **zero** times.
- `TgtCountry` vs point-in-zone **mismatch total = 144,672** (4.2% of assigned);
  pairs: LAOS->vietnam 37,183; SOUTH VIETNAM->cambodia 31,140; NORTH VIETNAM->laos
  30,226; SOUTH VIETNAM->laos 27,778; LAOS->cambodia 9,935; CAMBODIA->vietnam 5,365;
  NORTH VIETNAM->cambodia 2,228; CAMBODIA->laos 817. This **validates the seed
  spec's "point-in-zone authoritative, TgtCountry cross-check only" rule**: filtering
  or reassigning by `TgtCountry` would misplace/drop ~145k missions, plus 37,089
  assigned rows whose `TgtCountry` is empty/other.
- Largest valid-but-unassigned group: NORTH VIETNAM 82,564 (targets falling outside
  modern Vietnam's GADM zones — sea/China/coarse coords); reported, never repaired.
- Top densities (missions/km2, WGS84 geodesic area): overall VNM.50_1 QuangTri
  54.795361 (252,797 missions); **Laos top: LAO.12_1 Savannakhet 15.831911**
  (339,205 missions, 21,425.399 km2), then LAO.6_1 Khammouan 15.155476, LAO.18_1
  Xiangkhoang 12.886018. Cambodia pure-THOR top: KHM.25_1 TbongKhmum 6.371627.
- Full scan wall time (Task A, incl. weapons parsing): 201.9 s — seed runtime is
  single-digit minutes; keep the simple loop (no bulk optimisation).
- DB today (read-only check): 106 zones, `strike_density` non-NULL on 0/106.

## 1. Resolved conflicts between Task B and Task C (read before implementing)

1. **Dataset filename — Task C wins.** Profiles change to the real extracted name
   `data/thor/THOR_Vietnam_7_31_2013.csv`; there is **no rename step**. Task B §2's
   `Rename-Item ... thor_data_vietnam.csv` line is superseded — do not ship it in the
   script docstring/error. Task B's mechanism (resolve `strike_source.dataset`
   profile-relative, assert all 3 profiles agree) is unchanged.
2. **`country_filter` semantics — shape from C, non-filtering use from B.** Adopt
   C's `list<string>` shape (§3) as documented source values. But `seed_thor.py`
   must **never filter or assign rows by it** (B §4 + the 144,672-mismatch evidence
   above); the list documents which `TgtCountry` values the cross-check map expects
   for that profile. C §1.1's sentence "a THOR row belongs to the profile iff ..."
   is superseded by: "a row belongs to the zone its coordinates fall in".
3. **Cambodia demo pick — B's intersection rule wins over C's "top density" wording.**
   See §4: pick is **KHM.20_1 Rotanokiri**, NOT pure-THOR argmax KHM.25_1.
4. **Zero-mission zones -> 0.0 (B §5)** stands as contract, but note no real zone
   hits it (min is KHM.12_1 KrongPailin, 1 mission, 0.00093/km2). It still matters
   for `--country` scope and tests.

## 2. Seed script contract — NEW `scripts/seed_thor.py` (+ `seed_thor.ps1`/`.sh`)

Do NOT extend `seed_db.py` (65-min rerun, deletes/replaces craters; B §1). At most a
docstring pointer line there. API: `seed_thor(csv_path=None, db_path=None,
country=None, dry_run=False) -> dict`; helpers `parse_point`, `map_tgt_country`,
`load_zones`, `count_missions`, `main(argv=None) -> int`. CLI:
`python scripts/seed_thor.py [--country ID] [--csv PATH] [--db PATH] [--dry-run]`,
default = one all-country pass writing all 106 zones.

### 2.1 Input & extraction (manual step, never automated in Python)
- Canonical CSV = profiles' `strike_source.dataset` =
  `data/thor/THOR_Vietnam_7_31_2013.csv` (after §3 edits); all-country run asserts
  all profiles from `backend/app/profiles.py:list_countries()` agree; resolve as
  `REPO_ROOT / dataset`; `--csv` overrides (tests only).
- Missing-file error (exit 1) and docstring must print exactly:
  `& 'C:\Program Files\7-Zip\7z.exe' e ~/Downloads/THOR_Vietnam.zip -odata\thor`
  with the note that stdlib `zipfile`/Windows `tar` fail on Deflate64. Print actual
  size at startup; expected 2,627,971,171 B (mismatch = WARN, missing = exit 1).
- Read `open(csv_path, newline="", encoding="utf-8-sig")`, `csv.reader` +
  header->index map, `csv.field_size_limit(sys.maxsize)`, one streaming pass,
  progress every 500,000 rows. Assert before any DB write that headers
  `TgtCountry`, `TgtLatDD_DDD_WGS84`, `TgtLonDDD_DDD_WGS84` exist (else exit 1,
  DB untouched). Only these 3 columns are ever read.

### 2.2 Zones from DB (not GADM files)
`SELECT id, country, geom FROM zones [WHERE country = ?]` via
`backend/app/db.py:get_conn`; geom = `shapely.geometry.shape(json.loads(geom))`.
Fail before scanning on: missing DB, zero zones in scope, NULL/unparseable/invalid
geom, geodesic area <= 0. No schema `executescript` — an unseeded DB fails loudly.

### 2.3 Coordinate validity (`parse_point` -> `(lon, lat)` or first matching reason)
Strip both fields; INVALID if either is: `empty` (""), `null_literal`
(case-insensitive "NULL"), `unparseable` (`float()` raises or NaN/inf),
`out_of_range` (lat not in [-90,90] or lon not in [-180,180]), `zero_zero`
(lat == lon == 0.0 incl. `-0.0`). Never repaired, never assigned.
`NumWeaponsDelivered` (-1 sentinel), `WeaponType`, `MSNDate` are never inspected:
every valid-coord row = exactly 1 mission (U17).

### 2.4 Assignment — point-in-zone authoritative
`STRtree(zone geoms)`; per valid row `tree.query(Point(lon, lat), predicate="covers")`
(same as `seed_db.py:168`). 0 hits -> `outside_zones` (`outside_scope` under
`--country`); 1 hit -> that zone; >1 -> smallest `zones.id`, `multi_hit += 1`.
Cross-check map: `LAOS->laos`, `CAMBODIA->cambodia`,
`SOUTH VIETNAM|NORTH VIETNAM->vietnam`, `THAILAND->thailand`, else/empty->`unknown`
(compare `strip().upper()`). Mismatch (mapped in {laos,cambodia,vietnam} and != zone
country): keep point assignment, count in tgt->zone matrix, keep first 10 examples
`(row_no, TgtCountry, zone_id, lat, lon)`. Expected on real data: 144,672.

### 2.5 Density & the only write
```
area_km2       = abs(Geod(ellps="WGS84").geometry_area_perimeter(geom)[0]) / 1e6
strike_density = missions_assigned / area_km2        # missions per km2, U17
```
Zero missions -> `0.0` (real zero; THOR covers all 3 countries — docstring must state
this vs crater-hull NULL semantics). Accumulate all counts first; write only after
reconciliation (§2.6), in ONE transaction, the script's ONLY write:
```python
with conn:
    cur = conn.executemany("UPDATE zones SET strike_density = ? WHERE id = ?", rows)
```
Assert affected == zones in scope. Never touch `crater_evidence`, `exposure`,
`surveyed_status`, `priority_score`/`priority_rank`/`scored_at`, `craters`, `finds`.
`--dry-run` prints the would-write table instead. Idempotent pure function of
(CSV bytes, zone geoms). No migration (column in `schema.local.sql:11`, `schema.sql:17`).
Post-write: `PRAGMA integrity_check` == `ok`, `PRAGMA foreign_key_check` empty,
`COUNT(*) WHERE strike_density IS NULL` in scope == 0. `--country ID` (validated via
`load_country`) narrows STRtree+writes only; CSV still fully scanned.

### 2.6 Reconciliation (mismatch = exit 1 BEFORE writing) & expected real-run values
```
rows_read == assigned + invalid_coords + outside_zones      (+ outside_scope if --country)
assigned  == sum(missions over zones in scope)
```
Print in order: csv path+bytes; zones per country; rows_read; assigned; invalid total
with sub-reasons {empty, null_literal, unparseable, out_of_range, zero_zero};
outside_zones/scope; multi_hit; mismatch total + matrix + <=10 examples; per country:
zones, missions, density min/max, top-5 (id, missions, area_km2, density); zones
written; NULL strike_density remaining (0 in scope); integrity/fk; db path. Returned
dict mirrors counters (tests assert on it, not stdout). Manifest WARN block prints
claim vs observed (delta) from the §0 table — delta != 0 is a warning, observed is
truth, never an adjustment. **Acceptance for the first real all-country run:**
rows_read 4,670,422; assigned 3,419,286; invalid 1,130,146; outside_zones 120,990;
mismatch 144,672; zone-country missions KH 194,809 / LA 1,094,447 / VN 2,130,030;
106/106 densities non-NULL and > 0; top Laos LAO.12_1 15.831911 (small float-area
differences vs the scan are acceptable only if missions/zone match exactly).
Exit 0 only if reconciliation + rowcount + integrity all pass.

## 3. Profile JSON edits (exact)

`countries/laos.json:8-9`: `"dataset": "data/thor/THOR_Vietnam_7_31_2013.csv"`,
`"country_filter": ["LAOS"]`; delete `_todo` lines 16-17 (both THOR lines), keep :18.
`countries/cambodia.json:8-9`: same dataset, `"country_filter": ["CAMBODIA"]`;
delete `_todo` :17-18; set `demo_area` per §4 and delete `_todo` :16 in the same change.
`countries/vietnam.json:8-9`: same dataset,
`"country_filter": ["SOUTH VIETNAM", "NORTH VIETNAM"]` (old `"VIETNAM"` matches zero
rows); delete `_todo` :18, keep :16-17,19.
`countries/README.md:16`: append to the `strike_source` row: "`country_filter` is a
**list** of exact source values (THOR `TgtCountry`) the cross-check expects; zone
assignment is by coordinates, never by this filter. Vietnam needs two:
`["SOUTH VIETNAM", "NORTH VIETNAM"]`."
No live consumers break (grepped: `country_filter` occurs only in the 3 profiles,
README, WORKFLOW_SYNTHESIS; `backend/app/profiles.py` checks top-level presence only;
`/countries` API will emit a list instead of a string — note only). Recommended in
the same PR: nested validation in `load_country` (after :33) requiring
`strike_source.country_filter` to be a non-empty list of strings, `ValueError` else.

## 4. Cambodia demo province (U11) — DECIDED: `KHM.20_1` Rotanokiri

Rule (B §10, synthesis U11 + §2.4): among cambodia zones with
`crater_evidence IS NOT NULL`, highest `strike_density`; tie-break higher
`crater_evidence`, then `id` ASC. **Verified read-only in `data/clearfield.db`
today: exactly 2 of 25 Cambodia zones have non-NULL `crater_evidence`** —
`KHM.20_1` Rotanokiri = 0.4649884019 and `KHM.22_1` StoengTreng = 0.0150573178
(other 23 NULL). Scan densities: **KHM.20_1 = 1.391315 missions/km2** (16,391
missions, 11,780.939 km2) > KHM.22_1 = 0.790551 (9,503 missions). KHM.20_1 also wins
the crater tie-break. **Pick: `"demo_area": "KHM.20_1"` in `countries/cambodia.json`**,
delete its demo `_todo` line, flip `tests/test_profiles.py:15-18` — same commit.
Recorded but NOT picked: pure-THOR argmax `KHM.25_1` TbongKhmum, 6.371627/km2
(31,419 missions) — `crater_evidence` is NULL there today, so it is unscorable
(`scoring.py:40-42`); revisit only when a SAM crater source covers it. `seed_thor.py`
never writes profiles; parent applies this after the real seed run confirms the
densities above (or `--country cambodia --dry-run`).

## 5. Doc edits with real numbers filled in (apply only after the seed run lands)

Replacement fact everywhere: "strike_density landed (106/106 zones, 3,419,286
missions assigned of 3,540,276 with coords / 4,670,422 rows); exposure (OSM) has
NOT, so still 0 zones ranked."

- `docs/data-manifest.md:31` — replace the whole THOR line with:
  > - **THOR, Vietnam War** — data.world/datamil/vietnam-war-thor-data (free
  > data.world account required; **manual download only — not scriptable**,
  > `download_data.py` prints these steps and never fetches it). Downloaded file:
  > `THOR_Vietnam.zip` (457,332,289 B, local md5
  > `3b39a4921f7c0912fbe961184911167e`). The zip uses **Deflate64 (method 9):
  > Python `zipfile` and Windows `tar` cannot decompress it — extract with 7-Zip**:
  > `& 'C:\Program Files\7-Zip\7z.exe' e THOR_Vietnam.zip -odata\thor`. Single
  > member: `data/thor/THOR_Vietnam_7_31_2013.csv` (2,627,971,171 B; local md5
  > `939f28d770d9b3b9acd37553eab0fb85` — data.world publishes none). 85 columns
  > (BOM on first header name — open as `utf-8-sig`); we use `TgtCountry`
  > (`LAOS`/`CAMBODIA`/`SOUTH VIETNAM`/`NORTH VIETNAM`/`THAILAND`),
  > `TgtLatDD_DDD_WGS84`/`TgtLonDDD_DDD_WGS84` (literal `NULL` = no coords),
  > `MSNDate`, `NumWeaponsDelivered` (-1 = unknown), `WeaponType`. Rows total
  > 4,670,422 (1965-06-01..1975-06-30); missions WITH coordinates (counted by us,
  > superseding the data.world page's lower claims 1,041,519 / 1,620,422 /
  > 581,897 / 144,944 / 2,427): Laos 1,087,019; South Vietnam 1,658,608; North
  > Vietnam 607,482; Cambodia 147,097; Thailand 2,574. Records targets, not
  > impacts. Feeds `zones.strike_density` (missions per km2) via
  > `scripts/seed_thor.py`; 3,419,286 missions fall inside the 106 zones.
  Also `docs/data-manifest.md:3`: append `THOR (section 4) is the one manual exception.`
- `scripts/download_data.py` — do NOT add THOR to `FILES`. Docstring :7-8 ->
  "data.world/datamil/vietnam-war-thor-data -> THOR_Vietnam.zip (Deflate64; extract
  with 7-Zip, not zipfile) -> data/thor/THOR_Vietnam_7_31_2013.csv." Final print :85
  -> `MANUAL (not fetched): THOR - download THOR_Vietnam.zip (457,332,289 B) from
  data.world/datamil/vietnam-war-thor-data (free account), extract with 7-Zip
  (Deflate64 - Python zipfile/tar cannot): 7z e THOR_Vietnam.zip -odata/thor ->
  data/thor/THOR_Vietnam_7_31_2013.csv (2,627,971,171 B)`. Optional: if that CSV
  exists at that size, print `OK (present, manual) ...` instead.
- `docs/getting-started.md`: :5 -> "scores 0 zones until OSM lands (THOR
  strike_density seeded: 106/106 zones non-NULL)"; :12 add "THOR adds
  457,332,289 B (zip) + 2,627,971,171 B (csv)"; :33 -> "**THOR**: free data.world
  account, download THOR_Vietnam.zip (457,332,289 B), extract with 7-Zip (Deflate64
  — Explorer/zipfile/tar fail) into data/thor/ -> THOR_Vietnam_7_31_2013.csv
  (2,627,971,171 B). Then `python scripts/seed_thor.py` writes zones.strike_density."
  (stays under "Two manual steps" :32); :41 -> "# seed_db loads GADM + Barthelme;
  seed_thor adds THOR strike_density; exposure (OSM) stays NULL, so scoring still
  ranks 0 zones."; :42 "seed incl. THOR/OSM" -> "seed incl. OSM"; :65 -> "(0 scored
  until OSM exposure lands)"; :96 -> "Expected until OSM (exposure) is seeded — THOR
  strike_density is in; a NULL component means unscorable, never an imputed 0."
- `README.md`: :5 -> "No zone is rankable yet — exposure (OSM) has not landed (THOR
  strike density seeded: 3,419,286 missions over 106 zones)"; :9 REPLACE both stale
  page numbers with observed: Laos **1,087,019** recorded missions with coordinates,
  Cambodia **147,097**; :30 -> "Cambodia (KHM.20_1 Rotanokiri, picked per §4 of the
  THOR spec)"; :50 -> "# scores 0 until OSM lands (by design)"; :56 -> "THOR is a
  manual data.world download (never script-pinned; see manifest section 4);
  UXOTi_NPA, AMLID, and OSM downloads are not pinned yet."; add the
  `python scripts/seed_thor.py` step after :47.
- `data/README.md`: :5 -> "pinned files are MD5-checked against
  docs/data-manifest.md (GADM/THOR publish no source checksum; local MD5s recorded
  there)"; :7 -> "osm/, imagery/ do not exist yet" (+ refresh date); :13 ->
  `data/thor/  THOR_Vietnam_7_31_2013.csv (2,627,971,171 B; manual data.world
  THOR_Vietnam.zip + 7-Zip extract, see manifest section 4)`; :12 DB line ->
  "106 zones, 541,397 craters, strike_density on 106/106 zones".
- `WORKFLOW_SYNTHESIS.md` section 5: THOR sub-block (:527-538) marked RESOLVED with
  the §0 numbers; title "Blocked on META_API_KEY / THOR / OSM" -> "Blocked on
  META_API_KEY / OSM"; :530-531 strike_density NULL closes but "0 zones scorable,
  demo Moments 1-2 impossible" does NOT (OSM below); :532-533 demo_area closes with
  KHM.20_1; `agent/templates/en/survey-report.md:4` `{{ zone.strike_density }}`
  becomes fillable.
- Sweep for the same stale fact (Task B PR): `frontend/index.html:6`,
  `frontend/README.md:5`, `pipelines/scoring.py:15,121`, `scripts/seed_db.py:3,8-9`
  (docstring only), `tests/test_api.py:63` (asserts fixture `strike_density is None`
  — recheck if fixture becomes the real DB). Grep: `THOR+OSM|until THOR`.

## 6. Test list

`tests/test_seed_thor.py` (12, B §9; tmp-path DB from `db/schema.local.sql`, 4 square
fixture zones — 2 adjacent VN sharing an edge, 1 laos, 1 cambodia — preset
crater/exposure/surveyed + 1 finds row; fixture CSV with only the 3 required cols +
`NumWeaponsDelivered`,`WeaponType`,`MSNDate`; expected areas recomputed in-test
with `Geod`):
1. `test_density_is_missions_per_geodesic_km2` 2. `test_null_literal_empty_and_junk_coords_invalid`
3. `test_zero_zero_and_out_of_range_invalid` 4. `test_minus_one_weapons_still_one_mission`
5. `test_south_and_north_vietnam_both_assigned_no_filter_drop`
6. `test_tgtcountry_mismatch_point_wins_and_is_counted`
7. `test_boundary_point_assigned_once_smallest_zone_id`
8. `test_outside_and_thailand_reconciles` 9. `test_only_strike_density_column_written`
(zero-mission zone -> 0.0, not NULL) 10. `test_second_run_idempotent`
11. `test_missing_csv_and_bad_header_fail_before_write`
12. `test_country_flag_writes_only_that_country` (others NULL; out-of-scope counted
`outside_scope`).
Profile tests (same PR): `dataset` endswith `THOR_Vietnam_7_31_2013.csv` for all 3;
`country_filter` is a non-empty list; vietnam == `["SOUTH VIETNAM", "NORTH VIETNAM"]`;
if nested `load_country` validation ships, a string-filter fixture raises
`ValueError`. Flip `tests/test_profiles.py:15-18` for `demo_area == "KHM.20_1"`.
`tests/test_api.py:49-51` unaffected (ids only).

## 7. What remains blocked (THOR changes none of this)

- **OSM exposure**: `zones.exposure` NULL 106/106 => per synthesis §2.4 still **0
  scorable zones**, demo Moments 1-2 still impossible; §6-U9 exposure formula also
  unpinned (data alone won't fix it). `data/osm/` does not exist.
- **Crater coverage cap**: `crater_evidence` non-NULL on only 9 zones repo-wide
  (Cambodia 2/25: KHM.20_1, KHM.22_1) — a third independent cap on ranked zones
  even after OSM.
- **META_API_KEY**: `/explain` 501, Spark stub, km/lo templates, cached demo
  responses, SAM (`sam_segment.py` + `tiling.py` + absent `data/imagery/`) —
  untouched by THOR.
- Non-blockers still absent: PostGIS, UXOTi_NPA/AMLID, Barthelme
  `data.zip`/`models.zip`, Sentinel-2/NICFI/KH-9 imagery; G9 provenance/`seed_meta`
  table still open repo-wide (printed provenance only).

## 8. Parent execution order

1. §3 profile edits (+ optional `load_country` validation) 2. `scripts/seed_thor.py`
(+ wrappers) per §2 3. `tests/test_seed_thor.py` + profile-test additions (§6)
4. `python scripts/seed_thor.py --dry-run` — must reproduce §2.6 acceptance numbers
5. Real run `python scripts/seed_thor.py` 6. cambodia.json `demo_area` + test flip
(§4) 7. §5 doc edits + stale-fact grep sweep 8. Repo test suite green.
Non-goals: no META/Spark, no OSM/exposure, no scoring run, no PostGIS write path,
no `seed_db.py` logic changes, no automated THOR download/extraction.


