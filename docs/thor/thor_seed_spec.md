# THOR `strike_density` seed — exact implementation spec

No `META_API_KEY`, no network, no schema change. Inputs already verified by parent:
zip `THOR_Vietnam.zip` is Deflate64 (stdlib `zipfile`/`tar` cannot read it; 7-Zip can);
member `THOR_Vietnam_7_31_2013.csv`, 2,627,971,171 B, 85 cols, BOM on first header name.

## 1. Shape: NEW script `scripts/seed_thor.py` (+ `seed_thor.ps1`/`.sh` wrappers mirroring `seed_db.*`)

Do NOT extend `scripts/seed_db.py`. Justification, from that file's own contract:
- It runs ~65 min (`seed_db.py:26`), `DELETE`s/replaces all `barthelme_predictions`
  craters each run (`:146`), recomputes `crater_evidence` (`:205-211`), and hard-fails
  before any write if `predictions.zip`/GADM are missing (`:121-130`). Folding THOR in
  would make every THOR retry/rerun pay 65 min and put craters/finds-adjacent state at
  risk for a one-column update.
- THOR seeding is a pure, idempotent `UPDATE zones SET strike_density` (below): reruns
  must be cheap, independent, and incapable of touching `craters`, `finds`,
  `crater_evidence`, `exposure`, `surveyed_status`, or score columns.
- Precedent: `pipelines/scoring.py` is likewise a standalone single-writer runner over
  `backend/app/db.py:get_conn`. `seed_db.py` gets at most a docstring line pointing here;
  its "strike_density needs THOR" note (`:8-9`) stays true until this lands.
- Exposed, testable API (keyword args, tmp-path friendly like `score_country`):
  `seed_thor(csv_path=None, db_path=None, country=None, dry_run=False) -> dict`,
  helpers `parse_point(lat_s, lon_s)`, `map_tgt_country(s)`, `load_zones(conn, country)`,
  `count_missions(csv_path, zones)`, `main(argv=None) -> int`.

## 2. Input CSV and the extraction step (manual, documented, never automated in Python)

- Canonical input path = the profiles' `strike_source.dataset`:
  `data/thor/thor_data_vietnam.csv` (`countries/{laos,cambodia,vietnam}.json:8` — identical
  in all three). All-country run asserts all profiles from
  `backend/app/profiles.py:list_countries()` agree on this path; divergence = hard fail.
  Resolve as `REPO_ROOT / dataset` (`backend/app/config.py:6`). `--csv PATH` overrides
  (tests/fixtures only).
- Extraction is a documented manual step in the script docstring AND in its
  missing-file error (exact text implementers must ship):
  ```
  & 'C:\Program Files\7-Zip\7z.exe' e ~/Downloads/THOR_Vietnam.zip -odata\thor
  Rename-Item data\thor\THOR_Vietnam_7_31_2013.csv data\thor\thor_data_vietnam.csv
  ```
  Note in docstring: stdlib `zipfile` and Windows `tar` fail on Deflate64 (method 9) —
  do not "fix" by extracting in Python. Verify extracted size 2,627,971,171 B
  (print actual size at startup; size mismatch is a WARN, missing file is exit 1
  with the two commands above). `scripts/download_data.py` is NOT extended to fetch
  THOR (stays "THOR always stays manual", `download_data.py:7-8,85`); optionally its
  MANUAL line may gain "(extract with 7-Zip: Deflate64)".
- Reading: `open(csv_path, newline="", encoding="utf-8-sig")` (strips BOM),
  `csv.reader` with a header->index map (not `DictReader`: 85 cols x millions of rows).
  `csv.field_size_limit(sys.maxsize)`. Required headers, asserted before any DB write
  (missing/renamed = exit 1, DB untouched): `TgtCountry`, `TgtLatDD_DDD_WGS84`,
  `TgtLonDDD_DDD_WGS84`. Only these three columns are ever read; all other
  82 columns are ignored positions. One streaming pass; never load the file in memory.
  Progress print every 500,000 data rows.

## 3. Coordinate-validity rule (exact; `parse_point` returns `(lon, lat)` or a reason)

Strip whitespace from both fields first. A row's coords are INVALID (counted under
first matching sub-reason, never assigned, never repaired) if either field is:
1. `empty` — `""` after strip;
2. `null_literal` — case-insensitive `"NULL"` (THOR's missing marker);
3. `unparseable` — `float()` raises, or result is NaN/inf (covers `"NaN"`, `"NA"`, junk);
4. `out_of_range` — lat not in [-90, 90] or lon not in [-180, 180] (catches 999-style
   sentinels without enumerating them);
5. `zero_zero` — lat == 0.0 and lon == 0.0 (incl. `-0.0`): Gulf-of-Guinea sentinel,
   not a plausible Indochina target.

Nothing else invalidates a row. In particular `NumWeaponsDelivered` (-1 sentinel,
empty, anything) and `WeaponType`/`MSNDate` are never inspected: U17 unit is
missions, so every data row with valid coords counts as exactly 1 mission.

## 4. Assignment: point-in-zone authoritative; `TgtCountry` cross-check only

- Zones come from the DB, not GADM files (DB is what scoring reads):
  `SELECT id, country, geom FROM zones [WHERE country = ?]`, geom =
  `shapely.geometry.shape(json.loads(geom))`. Fail before scanning if: DB missing
  (`get_conn` raises), zero zones in scope, any NULL/unparseable/invalid geom, or any
  geodesic area <= 0. No schema `executescript` (unlike `seed_db.py:136`): a DB that
  was never seeded must fail loudly, not be half-created.
- `tree = STRtree([z.geom ...])`; per valid row
  `hits = tree.query(Point(lon, lat), predicate="covers")` — same predicate as
  `seed_db.py:168`, so boundary points are inside.
  - 0 hits -> `outside_zones` (or `outside_scope` under `--country`, section 6).
  - 1 hit -> that zone. >1 hits (shared border) -> smallest `zones.id` wins,
    `multi_hit += 1` (seed_db's overlap-area tie-break is degenerate for points;
    id ASC is its final tie-break, `:175-176`). Assigned exactly once, always.
- Cross-check map (constant in script; profiles' `country_filter` is stale —
  `VIETNAM` never occurs in THOR, `vietnam.json:9,18` — and must NOT be used as a
  row filter): `LAOS->laos`, `CAMBODIA->cambodia`,
  `SOUTH VIETNAM|NORTH VIETNAM->vietnam`, `THAILAND->thailand` (no zones; expected
  outside), anything else/empty -> `unknown`. Compare on `strip().upper()`.
- Mismatch = assigned zone's `country` != mapped country, counted only when mapped
  country is in {laos, cambodia, vietnam}. On mismatch: keep the point-in-zone
  assignment (never drop, never reassign, never fail the run); increment a
  tgt->zone-country matrix counter; collect first 10 examples
  `(row_no, TgtCountry, zone_id, lat, lon)` for the final print. Also count per mapped
  country: valid-coord rows that land outside all zones (border/coarse-coord noise).

## 5. Density definition and write rules (exact)

```
area_km2(zone)       = abs(Geod(ellps="WGS84").geometry_area_perimeter(geom)[0]) / 1e6
strike_density(zone) = missions_assigned(zone) / area_km2(zone)      # missions per km2, U17
```
Geod usage identical to `seed_db.py:52,101` (same areas `crater_evidence` uses).
- Zero assigned missions -> `strike_density = 0.0`, a real zero: THOR coverage is
  the whole file for all three countries, unlike crater hull coverage where NULL
  means unobserved (`seed_db.py:16-21`). State this NULL-vs-0 reasoning in the docstring.
- Accumulate all counts in memory first; write only after the full scan reconciles
  (section 7). Single transaction via `backend/app/db.py:get_conn(db_path)`:
  ```python
  with conn:
      cur = conn.executemany("UPDATE zones SET strike_density = ? WHERE id = ?", rows)
  ```
  Assert affected rows == zones in scope. This statement is the ONLY write in the
  script: never `crater_evidence`, `exposure`, `surveyed_status`,
  `priority_score`/`priority_rank`/`scored_at` (scoring runner's exclusive columns,
  `scoring.py:96-100`, `schema.sql:22-26`), never `craters`/`finds` rows.
  `--dry-run` skips the transaction and prints the would-write table.
- Idempotent: output is a pure function of (CSV bytes, zone geoms); rerun rewrites
  identical floats, touches nothing else. Column exists in both
  `schema.local.sql:11` and `schema.sql:17` — no migration.
- Post-write verification in-process: `PRAGMA integrity_check` == `ok`,
  `PRAGMA foreign_key_check` empty (pattern `seed_db.py:214-215`); re-SELECT
  `COUNT(*) WHERE strike_density IS NULL` per country in scope == 0.

## 6. CLI: all-country single pass by default; `--country` narrows writes only

```
python scripts/seed_thor.py [--country ID] [--csv PATH] [--db PATH] [--dry-run]
```
- Default: all profiles, one pass over the shared CSV, all 106 zones written. This is
  the recommended invocation: the CSV is one file shared by all three profiles, so
  per-country runs rescan 2.6 GB each to write a subset — no saving, triple the I/O.
- `--country ID` (validated via `load_country` before scanning; unknown id fails
  fast): STRtree/write scope = that country's zones only; CSV still fully scanned;
  valid points landing in no in-scope zone count as `outside_scope`, NOT
  `outside_zones`, so prints never claim other countries' missions fell "outside zones".
  Exists for safe first landings/debugging, mirroring scoring's per-country CLI shape
  (`pipelines/_profile.py:12-16`) — but note there scoring is per-country by contract;
  here all-country is the natural unit.
- Exit 0 only if reconciliation holds, write rowcount matches, integrity ok.
  Exit 1 (no/rolled-back write) on: missing CSV/DB, bad header, zero/invalid zones,
  reconciliation mismatch, rowcount mismatch, integrity failure.

## 7. Reconciliation prints (exact identities; a mismatch is exit 1, before writing)

Global, then per country (assigned grouped by zone.country; invalid/outside grouped
by mapped TgtCountry):
```
rows_read == assigned + invalid_coords + outside_zones            (+ outside_scope if --country)
assigned  == sum(missions over zones in scope)
```
Print, in order: csv path+bytes; zones in scope per country; rows_read; assigned;
invalid total with sub-reasons {empty, null_literal, unparseable, out_of_range,
zero_zero}; outside_zones/scope; multi_hit; mismatch total + matrix + <=10 examples;
per country: zones, missions assigned, density min/max, top-5 zones
(id, admin path not needed, missions, area_km2, density); zones written and
NULL strike_density remaining (must be 0 in scope); integrity/fk result; db path.
Non-fatal WARN block comparing valid-coords-per-TgtCountry against manifest claims
(verify-don't-trust): LAOS 1,041,519; SOUTH VIETNAM 1,620,422; NORTH VIETNAM 581,897;
CAMBODIA 144,944; THAILAND 2,427 — print `claim vs observed (delta)`; delta != 0 is a
warning with the observed number as truth, never an adjustment. Returned summary dict
mirrors these counters (tests assert on it, not on stdout text).

## 8. Runtime estimate

Zone load: 106 GeoJSON MultiPolygons + geodesic areas — seconds. Scan: unknown total
rows, >=3.39M with coords per manifest; `csv.reader`+index access over 85 cols runs
roughly 50-100k rows/s and Point+STRtree-covers roughly 20-50k rows/s on this class of
laptop (seed_db's 65 min is polygon reprojection of 541k features, not comparable).
Expect single-digit minutes end to end (~2-8 min for 4-6M rows); state as estimate in
docstring after first real run, with observed rows/s printed. Optimization, only if
observed >15 min: batch `shapely.points` + `STRtree.query_bulk(predicate="within")`
per 50k rows — but keep `covers`/smallest-id boundary semantics identical (bulk
boundary ties must be post-sorted by zone id), and keep the simple loop until measured.

## 9. Maintained tests: `tests/test_seed_thor.py` (12 tests, tiny in-test fixture)

Fixture (pattern `tests/test_scoring.py:81-92` tmp_path DB from
`db/schema.local.sql`): 4 square zones as GeoJSON MultiPolygons — two adjacent
vietnam squares sharing an edge (`VNM.A_1` west, `VNM.B_1` east), one laos, one
cambodia — with preset `crater_evidence`/`exposure`/`surveyed_status` and one finds
row. Fixture CSV written by the test with only the 3 required columns plus
`NumWeaponsDelivered`,`WeaponType`,`MSNDate` (proving extras ignored). Expected
areas recomputed in-test with `Geod`, never copied from the script's output.

1. `test_density_is_missions_per_geodesic_km2` — N points in one square;
   density == N / Geod area; unit is missions, not weapons.
2. `test_null_literal_empty_and_junk_coords_invalid` — `NULL`, `null`, `""`, `"abc"`
   rows counted under right sub-reasons, assigned nowhere.
3. `test_zero_zero_and_out_of_range_invalid` — `(0,0)`, `(-0.0,0)`, lat 999, lon -181.
4. `test_minus_one_weapons_still_one_mission` — `NumWeaponsDelivered=-1`, empty
   WeaponType: still counts exactly 1.
5. `test_south_and_north_vietnam_both_assigned_no_filter_drop` — SOUTH and NORTH
   VIETNAM rows inside VN squares both assigned (profile filter `VIETNAM` not applied).
6. `test_tgtcountry_mismatch_point_wins_and_is_counted` — `LAOS`-labelled point in the
   cambodia square lands in cambodia; mismatch counter/example recorded.
7. `test_boundary_point_assigned_once_smallest_zone_id` — point exactly on the shared
   VN edge -> `VNM.A_1`, `multi_hit == 1`, total assigned increments by 1.
8. `test_outside_and_thailand_reconciles` — THAILAND-labelled point outside all
   squares: `rows == assigned + invalid + outside` in returned summary.
9. `test_only_strike_density_column_written` — all other zone columns and the finds
   row byte-identical after run; zero-mission zone gets `0.0`, not NULL.
10. `test_second_run_idempotent` — full ordered zone dump identical after rerun.
11. `test_missing_csv_and_bad_header_fail_before_write` — nonzero/`FileNotFoundError`
    /`ValueError`; `strike_density` still NULL everywhere.
12. `test_country_flag_writes_only_that_country` — laos densities set, others remain
    NULL; VN/KH points counted `outside_scope`, not `outside_zones`.

## 10. Cambodia demo province (U11) — selection rule for the parent

Synthesis U11 (`WORKFLOW_SYNTHESIS.md:594-597`): pick from THOR strike density
intersected with whatever crater source covers it; never from Barthelme alone.
**Crater-coverage intersection IS required** for setting `demo_area` now, because a
zone with NULL `crater_evidence` is unscorable by contract (`scoring.py:40-42`,
synthesis section 2.4) and cannot be demoed as ranked; today only KHM.20_1/KHM.22_1
have non-NULL crater_evidence (synthesis U11, section 1 table: cambodia 2/25).
Rule: among cambodia zones with `crater_evidence IS NOT NULL`, pick highest
`strike_density`; tie-break higher `crater_evidence`, then `id` ASC. Parent must read
from Task A's `.uv-tmp/thor_scan.json`: the per-zone Cambodia breakdown (zone id ->
missions assigned and/or missions-per-km2) to rank KHM.20_1 vs KHM.22_1 (and to see
the pure-THOR argmax, recorded for when a SAM crater source covers it), plus the
scan's Cambodia valid-coords total cross-checked against the 144,944 manifest claim.
If thor_scan.json carries only per-country/per-TgtCountry aggregates (no per-zone
Cambodia densities), the rule cannot be applied from the scan alone — parent runs
`scripts/seed_thor.py --country cambodia --dry-run` (or reads DB densities after the
real all-country run); DB/`--dry-run` output is authoritative over scan summaries.
Applying the pick = set `countries/cambodia.json:demo_area` + update
`tests/test_profiles.py:15-18` in the same change (U10/U11 precedent); seed_thor
itself never writes profiles.

## 11. Explicit non-goals

No META/Spark, no OSM/exposure, no scoring run, no PostGIS write path (schema parity
means the same UPDATE ports later), no profile edits, no `seed_meta`/provenance table
(G9 still open repo-wide; printed provenance only), no changes to `seed_db.py` logic.


...[truncated 8121 chars]