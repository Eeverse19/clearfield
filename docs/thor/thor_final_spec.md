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
3. **Cambodia demo pick — owner override 2026-10-27.** Earlier draft (§4
   below) picked Rotanokiri via crater-coverage ∩ density. Owner confirmed
   **Tbong Khmum** (`KHM.25_1`, display `"Tbong Khmum"`). That is now the
   profile value. Rotanokiri remains the only high-density Cambodia zone
   with Barthelme crater coverage today.
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

## 4. Cambodia demo province (U11) — DECIDED: `KHM.25_1` Tbong Khmum

Owner confirmed 2026-10-27: `"demo_area": "Tbong Khmum"` in
`countries/cambodia.json` (display name; GADM `admin_name` is `TbongKhmum`,
zone `KHM.25_1`). Pure-THOR argmax in `thor_scan.json`: 31,419 missions,
6.371627/km².

Earlier crater ∩ density rule (kept for history, **not** the pick): among
cambodia zones with `crater_evidence IS NOT NULL`, highest `strike_density`
would have been `KHM.20_1` Rotanokiri. Verified read-only in
`data/clearfield.db`: exactly 2 of 25 Cambodia zones have non-NULL
`crater_evidence` — `KHM.20_1` Rotanokiri = 0.4649884019 and `KHM.22_1`
StoengTreng = 0.0150573178 (other 23 NULL, including Tbong Khmum). Tbong
Khmum is therefore unscorable (`scoring.py`) until a crater source covers
it; that is an imagery/SAM gap, not a reason to change the demo province.
`seed_thor.py` never writes profiles.

## 5. Doc edits with real numbers filled in (apply only after the seed run lands)

> **Superseded by §9.4/§9.7:** do not copy this section's 3,419,286 / "still 0 ranked" wording as seeded facts; use the corrected C-numbers (§9.4).

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
  Cambodia **147,097**; :30 -> "Cambodia (Tbong Khmum / KHM.25_1, owner-confirmed
  2026-10-27)"; :50 -> "# scores 0 until OSM lands (by design)"; :56 -> "THOR is a
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
  Tbong Khmum (`KHM.25_1`); `agent/templates/en/survey-report.md:4` `{{ zone.strike_density }}`
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
`ValueError`. Profile test already asserts `demo_area == "Tbong Khmum"`.
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
(Steps 2–5 are amended by §9 below — read §9 before implementing.)

## 9. Barthelme corrections — corrected seed contract (2026-10-28)

Reconciles §2 with Barthelme et al. 2024 (supplement Text S2 + code
`analysis.py`, github.com/pbarthelme/detecting-vietnam-war-bomb-craters) and with
verified probes of the local file `data/thor/THOR_Vietnam_7_31_2013.csv`
(4,670,422 rows, 85 cols; `.uv-tmp/probe_barthelme_full.py`,
`.uv-tmp/probe_ind60_bysource.py`, `.uv-tmp/probe_pin_counts.py`,
`.uv-tmp/probe_datum_pin.py`, all run read-only 2026-10-28). §9 supersedes §2
where they conflict, itemised in §9.7. What does **not** change: coordinates are
stored nowhere (datum changes zone assignment only); the only write is still
`UPDATE zones SET strike_density` after reconciliation (§2.5); `strike_density`
is still **missions/km² under U17** (§9.3) over WGS84 geodesic zone area;
pyproj is already a declared dependency (`pyproject.toml`: `pyproj>=3.7.2`;
verified locally pyproj 3.8.0 / shapely 2.2.0) — no new dependency.
Implementation and `--dry-run` may proceed on the pinned defaults below; the
**real run is gated on the four owner confirmations in §9.6**.

### 9.1 Datum transform (pinned; supersedes "coords are WGS84 as-is")

Source: Text S2 "Coordinate reference system" — the `*_wgs84` target columns
"despite their names, did not use the WGS84 coordinate reference system but
were instead provided in the Indian 1960 geodetic coordinate system
(EPSG:4131). We therefore converted these coordinates from EPSG:4131 to
EPSG:4326 (using EPSG:1542), which led to a shift of about 500 meters";
implemented in `analysis.py:91-98` (points built with `crs='EPSG:4131'`, then
`.to_crs('EPSG:4326')`). EPSG:1542 = "Indian 1960 to WGS 84 (2)"
(geocentric translations, `towgs84=198,881,317`, ellps `evrst30`→WGS84,
accuracy 44 m, EPSG area Vietnam onshore 14–18N / 105.61–109.36E; verified
locally via `TransformerGroup("EPSG:4131","EPSG:4326")`).

Pinned operation — force EPSG:1542 for **every** valid point, via its own
area of interest (never a bare `Transformer.from_crs(4131, 4326)`, which
silently no-ops outside 14–18N Vietnam: locally verified
`(102.6,17.97)->(102.6,17.97)`, `(106.5,10.5)` and `(105.8,21.0)` unchanged):

```python
from pyproj import Transformer
from pyproj.aoi import AreaOfInterest

def make_datum_transform():
    """EPSG:4131 (Indian 1960) -> EPSG:4326, forcing operation EPSG:1542."""
    t = Transformer.from_crs(
        "EPSG:4131", "EPSG:4326", always_xy=True,
        area_of_interest=AreaOfInterest(
            west_lon_degree=105.61, south_lat_degree=14.0,
            east_lon_degree=109.36, north_lat_degree=18.01))
    # Fail loud if PROJ ever selects the Ballpark/noop operation instead.
    for (lon, lat), (exp_lon, exp_lat) in [
            ((107.0, 16.8), (106.99580732082036, 16.801609276893966)),
            ((102.6, 17.97), (102.5963613440926, 17.97141995372316))]:  # forced
        got_lon, got_lat = t.transform(lon, lat)
        if abs(got_lon - exp_lon) > 1e-6 or abs(got_lat - exp_lat) > 1e-6:
            raise ValueError("EPSG:1542 datum transform not in effect")
    return lambda lon, lat: t.transform(lon, lat)
```

The two reference pairs were
observed locally with this exact construction (identical output from an
explicit `+proj=helmert +x=198 +y=881 +z=317` pipeline and from a
`towgs84=198,881,317` source CRS); shift at (107,16.8) is 481 m WNW
(dlon −0.004193, dlat +0.001609).

Where it sits: `parse_point` (§2.3) is unchanged — validity only, returns the
raw `(lon, lat)` parsed from `TgtLatDD_DDD_WGS84`/`TgtLonDDD_DDD_WGS84`. The
transform is applied in `count_missions` to a valid point **after** the
dedup (§9.2) and weapon (§9.3) gates and **before**
`tree.query(Point(lon, lat), predicate="covers")` (§2.4). Dropped rows are
never transformed. Source columns are the `*_WGS84` pair treated as
EPSG:4131 values (Barthelme-as-coded), so the §2.3 valid set is exactly
preserved (3,540,276 valid; re-verified by `probe_pin_counts.py`). The
`*_IND60` pair (cols 32/35) is **not** a counting input: locally
IND60-valid = 3,539,770 (515 rows valid only in the WGS84 pair, 9 only in
IND60 — unexplained), so sourcing from IND60 would change the valid set by
−506 for non-datum reasons (owner decision D2, §9.6).

### 9.2 B-52 dedup (pinned; supersedes "`MSNDate` never inspected")

Source: Text S2 "B-52 bombing records" — B-52 missions "recorded in both the
SEADAB and the SACCOACT databases starting from March, 1 1971"; SEADAB kept,
SACCOACT discarded (SACCOACT coords are on a ~1 nautical-mile grid). The code
is the operational rule (`analysis.py:151-153`):
`flag_no_duplicate = 1 - (sourcerecord == 'SACCOACT') * (msndate >= '1971-04-01')`
— all SACCOACT rows, no aircraft filter, implemented as a count flag (rows
not deleted). Locally corroborated: in this file a row-level match is
impossible (`SortieDuplicate` empty on all 4,670,422 rows; 0 shared
date+coord or date+MissionID keys between SEADAB and SACCOACT B-52≥1971), so
source-level exclusion is the only implementable reading.

Pinned rule:

```python
DEDUP_SOURCE = "SACCOACT"
DEDUP_CUTOFF = "19710401"   # MSNDate is fixed-width YYYYMMDD (sec. 0: 0 invalid)

is_deduped = (row[idx["SourceRecord"]].strip() == DEDUP_SOURCE
              and row[idx["MSNDate"]].strip() >= DEDUP_CUTOFF)
```

- Compare on the raw `YYYYMMDD` string (lexicographic = chronological at
  fixed width). **Never** compare a local `MSNDate` against `'1971-04-01'`
  (the analysis.py string format): every 1971 date would pass.
- No `Aircraft_Root` condition (Barthelme-as-coded). On the local file this
  is moot after validity: all 30,055 valid-coord rows the rule drops have
  `Aircraft_Root == 'B52'` (`probe_pin_counts.py`); SACCOACT KC135 rows do
  not survive coord validity past the cutoff.
- A deduped row is counted in the new counter **`deduped_saccoact`**, is not
  assigned to any zone, and contributes nothing to any density.
- Gate order (§9.4): coord validity first (`invalid_coords`), then dedup,
  then weapon gate, then datum transform, then point-in-zone — so
  `deduped_saccoact` counts valid-coord SACCOACT rows only.
  **Expected on the real file: `deduped_saccoact` = 30,055.**
- Cutoff conflict, stated loudly: supplement text says 1971-03-01, code
  implements 1971-04-01. The code date is pinned (it reproduces the published
  results); the difference is exactly **796** valid-coord SACCOACT rows
  (30,851 at March vs 30,055 at April, `probe_pin_counts.py`). `--dry-run`
  must also print the diagnostic `deduped_saccoact_march_variant` (= 30,851
  expected) so flipping the constant is a one-line owner call (decision D3).

### 9.3 Weapon rule (U17 retained — filter NOT applied; variant is an owner decision)

Barthelme's rule **is** pinned in their sources but is **not** pinned for
this file/metric, so per the no-invention rule it is not applied:
**every deduped valid-coord row = exactly 1 mission (U17 stands);
`WeaponType`, `NumWeaponsDelivered`, `NumOfAcft` and all `Weapons*Weight`
columns are never inspected; the new counter `weapon_excluded` exists in the
identity (§9.4) and is always 0 under the pinned rule.**

Why the filter is not portable without an owner decision (all verified):
(a) **Metric conflict** — Barthelme's filtered quantity is *weapons
delivered* (`ct = numweaponsdelivered * flag_filtered`, `analysis.py:185`);
ClearField `strike_density` is missions/km² (U17). Filtered-missions/km² vs
weapons/km² vs unfiltered missions/km² are three different metrics.
(b) **Unpinned local mapping** — the imputation's 820-lb split tests a
hyphenated `valid_aircraft_root` (`'B-52'`, …) that does not exist in the
local file (local `Aircraft_Root` col 13: `'B52'`, `'KC135'`, …; no
`ValidAircraftRoot`/`MFUNC_DESC_CLASS` columns in the 85-col header), so the
rule as-coded matches almost nothing locally until a ClearField-authored
value map is invented. (c) **Scale** — applying the full Barthelme filter to
local mission counting keeps 1,112,529 of 3,540,276 valid rows (discards
68.6%, `probe_barthelme_full.py`).

The variant, recorded exactly for the owner (Text S2 + `analysis.py:44-85,
122-161`; if ever enabled it is a spec amendment, not an implementer choice):
keep a row iff `weapontype_imp` is one of 22 general-purpose bomb types —
CACTA: `500LB GP MK-82`, `750LB GP M-117`, `250LB MK-81`, `500LB GP M-64`,
`250LB M-57`, `200/260 M81/88`, `1000LB MK-83`, `100LB GP M-30`,
`1000LB GP M-65`, `2000LB MK-84`, `2000LB M-66`, `3000LB M-118`; SACCOACT:
`MK82 B`, `750 GP`, `M64A1`, `MK83 B`; SEADAB: `MK 82 GP BOMB (500) LD`,
`M117 GP BOMB (750) LD`, `MK81 GP BOMB (250)`, `MK82 GP BOMB (500) HD`,
`MK 82 GP BOMB (500)`, `MK83 GP BOMB (1000)` (union tested, source not
checked) — **and** `numweaponsdelivered / numofacft <= 108`. `weapontype_imp`
= `weapontype` (missing → `'N/A'`), overwritten wherever the estimated
per-weapon weight (`weaponsloadedweight / numweaponsdelivered / 10` when both
> 0, else `weapontypeweight`) exactly equals 260 → `MK81 GP BOMB (250)`,
531 → `MK 82 GP BOMB (500) LD`, 571 → `MK82 GP BOMB (500) HD`,
1100 → `MK83 GP BOMB (1000)`, or 820 → `M117 GP BOMB (750) LD` iff aircraft
root in {`A-1`,`A-37`,`B-52`,`B-57`,`F-100`,`F-105`,`F-5`} else
`CBU49 AN PR MINE` (not in the 22, i.e. excluded). Unknown/unimputed weapon
rows fail the filter (Barthelme count them only in a robustness subset).
Note: no local row has `NumWeaponsDelivered == -1` (full probe), so §2.3's
"-1 sentinel" remark and §6 test 4 are fixture-only under U17.

### 9.4 Revised reconciliation & acceptance (supersedes §2.6)

Identity (mismatch = exit 1 BEFORE writing), with gates applied per row in
the pinned order validity → dedup → weapon → transform → assign:

```
rows_read == assigned + invalid_coords + outside_zones
             + deduped_saccoact + weapon_excluded      (+ outside_scope if --country)
assigned  == sum(missions over zones in scope)
```

`weapon_excluded` must print/return 0 under §9.3. The returned dict gains
`deduped_saccoact`, `weapon_excluded`, `baseline_assigned`, `datum_assigned`
(and diagnostic `deduped_saccoact_march_variant`, `ind60_ne_wgs84`).

The §2.6 numbers become the **uncorrected baseline** (A), recomputed in the
same pass (raw `*_WGS84` point, no dedup, no weapon gate — a second
`tree.query` per valid row) and compared exactly:

- **A — baseline (all-country run: must match §2.6 exactly, else exit 1
  before write; under `--country` A is tallied in-scope only and reported,
  not compared to these totals):**
  rows_read 4,670,422; `baseline_assigned` 3,419,286; baseline outside
  120,990; `invalid_coords` 1,130,146; baseline `TgtCountry` mismatch
  144,697; baseline zone-country missions KH 194,836 / LA 1,094,447 /
  VN 2,130,003. (Zone-country and mismatch baselines require tallying A per
  zone in the dry-run/report only; A never writes densities.) The mismatch
  and zone-country values supersede §2.6 (144,672; KH 194,809 / VN 2,130,030):
  the §0 scan took the first `covers` hit in STRtree order for points exactly
  on a shared border, while §2.4 mandates smallest `zones.id`; 70 such points
  change owner (net KH +27 / VN −27, mismatch +25), totals identical.
  Observed on the first dry-run, 2026-10-28.
- **B — datum-only:** `datum_assigned` = assignments of the transformed
  point, dedup not applied. Datum delta = B − A (report totals; per-zone B
  not required).
- **C — corrected (final; the only counts written):** transformed point,
  deduped rows excluded. `assigned` = C; dedup delta = C − B = −(deduped
  rows whose transformed point lands in a zone). Total delta C − A must equal
  datum delta + dedup delta exactly — every delta vs §2.6 is thereby
  explained (weapon delta = 0 by §9.3).

**Revised acceptance for `--dry-run`:** A-numbers exact as above;
`deduped_saccoact` = 30,055; `deduped_saccoact_march_variant` = 30,851;
`weapon_excluded` = 0; if the `TgtLatDD_DDD_IND60`/`TgtLonDDD_DDD_IND60`
columns are present, also report `ind60_ne_wgs84` (valid rows whose IND60
strings differ from the WGS84 pair; expected **1,246,748** — diagnostic for
decision D2, never a counting input). Real-run alignment (2026-10-28):
the seed observed **1,247,263**, +515 vs the probe expectation, a
definition difference, not a data change. The probe
(`.uv-tmp/probe_pin_counts.py`, behind the §9.1/§9.4 figure) counts only
rows valid in **both** pairs (`wv and iv`) whose strings differ, whereas
`scripts/seed_thor.py` counts every row whose `*_WGS84` pair passes
`parse_point` and whose stripped IND60 strings differ — without requiring
the IND60 pair itself to be valid. The +515 is exactly the 515 rows valid
only in the WGS84 pair (§9.1), all of which necessarily string-differ from
their (invalid) IND60 pair. Diagnostic only, never a counting input (as
above). C-numbers (assigned, outside,
corrected mismatch total + matrix, per-country missions, density min/max,
top-5) are **reported, not pre-pinned** — they become the real-run
acceptance only after the owner confirms D1–D4 (§9.6) on the dry-run
output. §2.6's "106/106 densities > 0, Laos top LAO.12_1 15.831911" is
superseded for corrected densities (it remains the baseline-A expectation);
§5's replacement fact must use C-numbers once known, not 3,419,286.
Mismatch counting (§2.4) runs on C for the headline matrix and on A for the
baseline anchor. Short rows are padded with `""` to header width before any
indexing (scanner behaviour §0; required columns now include the low-index
`SourceRecord` col 0 and `MSNDate` col 2, header-asserted together with
`TgtCountry` + the WGS84 pair before any DB write).

### 9.5 Test strategy under the transform (pinned: injectable transformer)

`seed_thor(csv_path=None, db_path=None, country=None, dry_run=False,
datum_transform=None)` — `None` builds `make_datum_transform()` (§9.1); any
callable `(lon, lat) -> (lon, lat)` may be injected. The §6 fixtures stay
synthetic WGS84 squares, unchanged: tests inject the identity transform
(`lambda lon, lat: (lon, lat)`) so fixture geometry/areas need no datum
awareness. Fixture CSVs must add the two new required columns
(`SourceRecord`, `MSNDate`; use non-dedup values e.g. `SEADAB`/`19700101`
except where the test targets dedup). The 12 §6 tests stand; add:

13. `test_dedup_drops_saccoact_from_19710401_only` — SACCOACT `19710401`
    dropped (`deduped_saccoact` increments, zone gets no mission); SACCOACT
    `19710331` and SEADAB `19710401` counted; identity still closes.
14. `test_default_transform_is_forced_epsg1542` — `make_datum_transform()`
    maps (107.0, 16.8) and out-of-area (102.6, 17.97) to the §9.1 reference
    pairs within 1e-6 (guards the silent-noop trap; no CSV/DB needed).
15. `test_transform_applied_before_assignment` — inject a stub shift
    (e.g. lon + 0.01) moving a fixture point across a zone edge; assignment
    follows the shifted point, and stored DB values are densities only.
16. `test_baseline_and_corrected_counts_reconcile` — fixture with one
    deduped row + the stub shift: A/B/C totals satisfy
    C − A = (B − A) + (C − B) and the §9.4 identity with
    `weapon_excluded == 0`.

Test 4 (`test_minus_one_weapons_still_one_mission`) stands verbatim (U17).

### 9.6 Owner decisions gating the real run (dry-run may proceed)

- **D1 — Forcing EPSG:1542 outside 14–18N Vietnam.** Pinned default: force
  everywhere (all of Laos/Cambodia, N+S Vietnam). This extrapolates the
  DMA-Vnm operation beyond its EPSG area and beyond Barthelme's two
  validation areas; the alternative (bare per-point PROJ selection) applies
  **no** shift to most Laos/Cambodia zones, i.e. silently seeds them
  uncorrected. Owner to confirm forcing on the dry-run deltas.
- **D2 — Source columns `*_WGS84` (pinned) vs `*_IND60`.** Locally the
  WGS84 pair is a pure IND60 copy for SEADAB/SACCOACT, but ~1,246,748 valid
  CACTA rows already carry a partial ~320 m WNW shift in the WGS84 pair
  that is **not** EPSG:1542 (0/600 sampled rows match 1542(IND60)); the
  pinned rule partially double-shifts those rows (Barthelme-as-coded —
  their data.world file is a different distribution and their code never
  reads IND60 columns). Sourcing from IND60 avoids that but changes the
  valid set by −506 (§9.1). Owner to rule, or commission a
  data.world-vs-local provenance check.
- **D3 — Dedup cutoff 1971-04-01 (code, pinned) vs 1971-03-01 (text).**
  796 valid rows. Owner to confirm before the real run.
- **D4 — Weapon filter (§9.3 variant).** Pinned default: not applied (U17
  missions/km²). Enabling it requires the owner to choose the metric
  (filtered missions/km² vs weapons/km² — the latter redefines
  `zones.strike_density` and its docstring everywhere) and to approve a
  locally-authored `Aircraft_Root` value map for the 820-lb split.

**Resolution (2026-10-28):** owner confirmed all pinned defaults — D1+D2
`*_WGS84` columns with forced EPSG:1542 everywhere, D3 dedup cutoff
1971-04-01 (code), D4 weapon filter OFF (U17 missions/km²) — and the real
run + scoring executed with corrected C-numbers: rows 4,670,422, assigned
3,401,836, invalid 1,130,146, outside 108,385, `deduped_saccoact` 30,055
(March variant 30,851), `weapon_excluded` 0; per-country missions cambodia
191,184 / laos 1,090,845 / vietnam 2,119,807; `strike_density` on 106/106
zones; scoring laos 4/18, cambodia 2/25, vietnam 0/63.

### 9.7 Superseded text (exact)

- §2.1 "Only these 3 columns are ever read" → 5 counting columns
  (`TgtCountry`, `SourceRecord`, `MSNDate`, WGS84 lat/lon) + 2 optional
  diagnostic IND60 columns; header assert covers the 5.
- §2.3 "`NumWeaponsDelivered` …, `WeaponType`, `MSNDate` are never
  inspected: every valid-coord row = exactly 1 mission" → `SourceRecord` +
  `MSNDate` are inspected for the §9.2 dedup gate only; the rest stands.
- §2.4 assignment point → the §9.1-transformed point.
- §2.6 identity + "Acceptance for the first real all-country run" → §9.4
  (old numbers demoted to baseline A).
- §5 replacement fact / mission totals → use corrected C-numbers (§9.4);
  do not publish 3,419,286 / LAO.12_1 15.831911 as seeded facts.
- §6 fixture ("only the 3 required cols" + 12 tests) → §9.5 (5 cols, 16
  tests, injectable transform).
- §8 step 4 → dry-run must satisfy §9.4 acceptance; step 5 (real run)
  additionally requires D1–D4 confirmation recorded.


