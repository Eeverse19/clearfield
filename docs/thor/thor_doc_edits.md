# THOR doc/profile edits — exact old -> new (Task C, READ-ONLY survey)

Verified THOR facts (parent-supplied): zip `THOR_Vietnam.zip` 457,332,289 B, ZIP
Deflate64 (method 9) — stdlib `zipfile` and Windows `tar` CANNOT decompress it;
7-Zip (`C:\Program Files\7-Zip\7z.exe`) can. Single member
`THOR_Vietnam_7_31_2013.csv`, 2,627,971,171 B, 85 cols (BOM on first name).
Key cols: `TgtCountry` (seen: `SOUTH VIETNAM`, `LAOS`; manifest claims also
`NORTH VIETNAM`, `CAMBODIA`, `THAILAND`), `TgtLatDD_DDD_WGS84` /
`TgtLonDDD_DDD_WGS84` (literal `NULL` = missing), `MSNDate` YYYYMMDD,
`NumWeaponsDelivered` (-1 sentinel), `WeaponType`.
All counts/densities below stay `<from thor_scan.json>` — Task A owns values.
"Seeded" below = Task B loader has written `zones.strike_density`
(missions/km2, WORKFLOW_SYNTHESIS §2/U17). Extraction alone changes no DB state.

---

## 1. Profiles: dataset filename + country_filter string -> list

### 1.1 Proposed shape (one breaking change, no live consumers — see 1.3)

Keep the key name `country_filter`; change its type from `string` to
`list<string>`, uniformly for every country (even single-value ones).
Semantics: a THOR row belongs to the profile iff
`row["TgtCountry"] in profile["strike_source"]["country_filter"]`.
Do NOT add a plural alias (`country_filters`) and do NOT keep a string form:
no code reads it today, so one clean shape costs nothing and prevents a
`isinstance(str|list)` branch in the future loader. Tier-2/3 sources
(UCDP/ACLED) reuse the same list-of-source-values meaning.

### 1.2 Exact edits, all three profiles (lines 6-10 in each today)

`countries/laos.json:8-9`
```diff
-    "dataset": "data/thor/thor_data_vietnam.csv",
-    "country_filter": "LAOS"
+    "dataset": "data/thor/THOR_Vietnam_7_31_2013.csv",
+    "country_filter": ["LAOS"]
```

`countries/cambodia.json:8-9`
```diff
-    "dataset": "data/thor/thor_data_vietnam.csv",
-    "country_filter": "CAMBODIA"
+    "dataset": "data/thor/THOR_Vietnam_7_31_2013.csv",
+    "country_filter": ["CAMBODIA"]
```

`countries/vietnam.json:8-9` — the reason for the list: modern Vietnam is TWO
`TgtCountry` values; old `"VIETNAM"` matches zero rows.
```diff
-    "dataset": "data/thor/thor_data_vietnam.csv",
-    "country_filter": "VIETNAM"
+    "dataset": "data/thor/THOR_Vietnam_7_31_2013.csv",
+    "country_filter": ["SOUTH VIETNAM", "NORTH VIETNAM"]
```

`countries/README.md:16`
```diff
-| `strike_source` | `{type, dataset, country_filter}` — THOR for Tier 1, UCDP/ACLED later |
+| `strike_source` | `{type, dataset, country_filter}` — THOR for Tier 1, UCDP/ACLED later. `country_filter` is a **list** of exact source values (THOR `TgtCountry`); a row matches if its value is in the list. Vietnam needs two: `["SOUTH VIETNAM", "NORTH VIETNAM"]`. |
```

`_todo` cleanup in the same edit (else profiles lie after extraction):
- `countries/laos.json:16-17` — delete both lines:
  `"THOR csv requires a manual data.world download into data/thor/",` and
  `"Confirm exact THOR country-column value once the csv header is available",`
  (header seen: `TgtCountry`=`LAOS`; manual-download fact moves to manifest §4.)
  Keep line 18 (GADM/OSM pinning) — still open for OSM.
- `countries/cambodia.json:17-18` — delete both THOR lines (same strings).
  Keep `:16` demo_area line but it is now actionable, see §4; when picked:
  `"demo_area": null` -> `"demo_area": "<from thor_scan.json: top Cambodia province by strike density>"`,
  delete `:16`, and flip `tests/test_profiles.py:15-18` (see 1.3).
- `countries/vietnam.json:18` — delete:
  `"THOR csv requires a manual data.world download into data/thor/; South/North Vietnam rows are separate THOR targets and the filter must map both",`
  (now expressed by the two-element list). Keep `:16-17,19`.

### 1.3 Every reader of `country_filter` / `strike_source` today (grepped 2026-10-26)

`country_filter` occurrences — ONLY these 5, no code reads the value:
`countries/laos.json:9`, `countries/cambodia.json:9`, `countries/vietnam.json:9`
(data), `countries/README.md:16` (doc), `WORKFLOW_SYNTHESIS.md:534` (doc).

`strike_source` / profile consumers, and impact of string->list:
- `backend/app/profiles.py:7-17` `REQUIRED_FIELDS` includes `"strike_source"`;
  `load_country:29` checks only top-level presence (`f not in profile`).
  No nested validation of `type`/`dataset`/`country_filter` exists.
  => string->list breaks nothing. RECOMMENDED (same PR as Task B loader, not
  required for the doc edit): add nested validation in `load_country` after
  line 33, e.g. `ss = profile["strike_source"]; if not (isinstance(ss, dict)
  and isinstance(ss.get("country_filter"), list) and ss["country_filter"]
  and all(isinstance(v, str) for v in ss["country_filter"])): raise ValueError(...)`
  so a future profile cannot silently regress to a string.
- `backend/app/main.py:63-70` `/countries`, `/countries/{id}` return the whole
  profile dict verbatim (`list_countries()` / `_country_or_404`) => API JSON
  will emit a list where it emitted a string. No field-level access anywhere,
  frontend does not read profiles (grep: no `strike_source`/`country_filter`
  in `frontend/`). API-shape note only.
- `pipelines/_profile.py:12-16` `country_arg()` returns `load_country(...)`;
  consumers `pipelines/scoring.py:114`, `tiling.py:8`, `sam_segment.py:13`
  use only `profile['id']`/`demo_area` => unaffected. The future THOR loader
  is the FIRST real reader: it must do membership, never `==`.
- `scripts/seed_db.py:46,84-86` iterates `list_countries()` but reads only
  `boundaries.country_code` + `id` => unaffected. (Its docstring `:3,8-9`
  "without ... THOR / strike_density needs THOR" goes stale only when Task B
  lands in this script or a sibling — Task B owns that line.)
- `tests/test_profiles.py:1,9-12` asserts `REQUIRED_FIELDS` presence only => passes
  unchanged. RECOMMENDED new assertions (Task B PR): dataset endswith
  `THOR_Vietnam_7_31_2013.csv`; `country_filter` is a non-empty list;
  `load_country("vietnam")["strike_source"]["country_filter"] == ["SOUTH VIETNAM", "NORTH VIETNAM"]`.
  SEPARATE pre-existing pin: `tests/test_profiles.py:15-18`
  (`test_laos_demo_area_and_cambodia_pending`, comment "picked from THOR
  density once data exists") must flip when Cambodia `demo_area` is set from
  `<from thor_scan.json>` — until then it still passes.
- `tests/test_api.py:49-51` `test_countries` checks ids only => unaffected.

---

## 2. `docs/data-manifest.md` §4 THOR entry rewrite + downloader message

### 2.1 Replace `docs/data-manifest.md:31` entirely

Old (whole line 31):
> - **THOR, Vietnam War** — data.world/datamil/vietnam-war-thor-data, file `thor_data_vietnam.csv` (~1.5 GB). Free data.world account required. Missions with coordinates: Laos 1,041,519; South Vietnam 1,620,422; North Vietnam 581,897; Cambodia 144,944; Thailand 2,427. Records targets, not impacts.

New (verbatim replacement; fill placeholders from Task A before commit):
> - **THOR, Vietnam War** — data.world/datamil/vietnam-war-thor-data (free data.world account required; **manual download only — not scriptable**, `download_data.py` prints these steps and never fetches it). Downloaded file: `THOR_Vietnam.zip` (457,332,289 B). The zip uses **Deflate64 (method 9): Python `zipfile` and Windows `tar` cannot decompress it — extract with 7-Zip**: `& 'C:\Program Files\7-Zip\7z.exe' e THOR_Vietnam.zip -odata\thor` (or `7z e -so` to stream). Single member: `data/thor/THOR_Vietnam_7_31_2013.csv` (2,627,971,171 B; local md5 `<from thor_scan.json, if computed — data.world publishes none>`). 85 columns (BOM on first header name — open as `utf-8-sig`); we use `TgtCountry` (`LAOS` / `CAMBODIA` / `SOUTH VIETNAM` / `NORTH VIETNAM` / `THAILAND`), `TgtLatDD_DDD_WGS84`/`TgtLonDDD_DDD_WGS84` (literal `NULL` = no coords), `MSNDate`, `NumWeaponsDelivered` (-1 = unknown), `WeaponType`. Rows total `<from thor_scan.json>`; missions WITH coordinates: Laos `<from thor_scan.json>`; South Vietnam `<from thor_scan.json>`; North Vietnam `<from thor_scan.json>`; Cambodia `<from thor_scan.json>`; Thailand `<from thor_scan.json>` (data.world page claimed 1,041,519 / 1,620,422 / 581,897 / 144,944 / 2,427 — superseded by the scan). Records targets, not impacts. Feeds `zones.strike_density` (missions per km2).

Also `docs/data-manifest.md:3` — one clause goes stale once THOR is present
locally but still manual; keep as-is EXCEPT it must not imply THOR is
reproduced by the script. It already says "reproduces the pinned files" —
append after that clause: `THOR (§4) is the one manual exception.`

### 2.2 `scripts/download_data.py` — what it should print now (still NOT pinned)

Do NOT add THOR to `FILES` (`:20-31`): no direct URL, login-gated, and the
stdlib script could not unzip Deflate64 anyway. Two text edits only:

Docstring `:7-8`:
```diff
-not pinned yet, and THOR always stays manual (free data.world account):
-data.world/datamil/vietnam-war-thor-data -> data/thor/thor_data_vietnam.csv.
+not pinned yet, and THOR always stays manual (free data.world account):
+data.world/datamil/vietnam-war-thor-data -> THOR_Vietnam.zip (Deflate64;
+extract with 7-Zip, not zipfile) -> data/thor/THOR_Vietnam_7_31_2013.csv.
```

Final print `:85`:
```diff
-    print("MANUAL (not fetched): data/thor/thor_data_vietnam.csv (data.world account required)")
+    print("MANUAL (not fetched): THOR - download THOR_Vietnam.zip (457,332,289 B) from "
+          "data.world/datamil/vietnam-war-thor-data (free account), extract with 7-Zip "
+          "(Deflate64 - Python zipfile/tar cannot): 7z e THOR_Vietnam.zip -odata/thor "
+          "-> data/thor/THOR_Vietnam_7_31_2013.csv (2,627,971,171 B)")
```
Optional same-line improvement (implementer's call): if
`data/thor/THOR_Vietnam_7_31_2013.csv` exists with size 2,627,971,171, print
`OK (present, manual) data/thor/THOR_Vietnam_7_31_2013.csv` instead.

---

## 3. Lines that go stale once THOR is extracted + seeded

Apply ONLY after Task B seeds `zones.strike_density`; the replacement fact in
every row is "strike_density landed; exposure (OSM) has NOT, so still 0 zones
ranked" unless noted. Numbers = `<from thor_scan.json>`.

### `docs/getting-started.md`
- `:5` `Section 5: scoring.py works and correctly scores 0 zones until THOR+OSM land`
  -> `...scores 0 zones until OSM lands (THOR strike_density seeded <date>: <from thor_scan.json: zones with strike_density>/106 zones non-NULL)`.
- `:12` `~8 GB if Barthelme data.zip/models.zip and THOR are also fetched`
  -> keep, but THOR is now concrete: `THOR adds 457,332,289 B (zip) + 2,627,971,171 B (csv)`.
- `:33` `**THOR** (thor_data_vietnam.csv, ~1.5 GB): create a free account at data.world, download from data.world/datamil/vietnam-war-thor-data, place the file in data/thor/.`
  -> `**THOR**: create a free account at data.world, download THOR_Vietnam.zip (457,332,289 B) from data.world/datamil/vietnam-war-thor-data, extract with 7-Zip (Deflate64 — Explorer/zipfile/tar fail) into data/thor/: & 'C:\Program Files\7-Zip\7z.exe' e THOR_Vietnam.zip -odata\thor → data/thor/THOR_Vietnam_7_31_2013.csv (2,627,971,171 B). Then <Task B seed command> writes zones.strike_density.`
  The step STAYS in "Two manual steps the script cannot do for you" (`:32`) — still manual, only the filename/extraction changes.
- `:41` `# Loads NO OSM/THOR yet: strike_density and exposure stay NULL, so scoring ranks 0 zones.`
  -> `# seed_db loads GADM + Barthelme (+ THOR strike_density via <Task B step>); exposure (OSM) stays NULL, so scoring still ranks 0 zones.`
  (Exact wording depends where Task B puts the loader — flag for Task B.)
- `:42` `# Target: ... seed incl. THOR/OSM.` -> `# Target: ... seed incl. OSM.` (PostGIS target itself unchanged.)
- `:65` `# works: deterministic ranking -> local DB (0 scored until THOR+OSM)` -> `(0 scored until OSM exposure lands)`.
- `:96` `Expected until THOR (strike_density) and OSM (exposure) are seeded` -> `Expected until OSM (exposure) is seeded — THOR strike_density is in; a NULL component means unscorable, never an imputed 0.`

### `README.md`
- `:5` `No zone is rankable yet — strike density (THOR) and exposure (OSM) have not landed`
  -> `No zone is rankable yet — exposure (OSM) has not landed (THOR strike density seeded: <from thor_scan.json: missions-with-coords counted> missions over <from thor_scan.json> zones)`. Rest of the status line (META_API_KEY, no live calls, Barthelme vs Xieng Khouang) unchanged.
- `:9` problem numbers (`1,041,519 recorded US bombing missions`, `Cambodia (144,944 missions...)`) — re-verify against `<from thor_scan.json>`; keep only if scan confirms, else replace both with scan values. Do not leave data.world's claimed numbers once we have counted rows ourselves.
- `:30` `Cambodia (one province, picked from THOR density)` -> `Cambodia (<from thor_scan.json: picked province>)` once `demo_area` is set; until then unchanged.
- `:50` `# scores 0 until THOR+OSM land (by design)` -> `# scores 0 until OSM lands (by design)`.
- `:56` `THOR, UXOTi_NPA, AMLID, and OSM downloads are not pinned yet.`
  -> `THOR is a manual data.world download (never script-pinned; see manifest §4); UXOTi_NPA, AMLID, and OSM downloads are not pinned yet.`
  Also `:56` first sentence "All datasets are public and reproduced by download_data.sh" already overclaims for THOR — the replacement above fixes it; do not strengthen it.
- NOT stale: `:13` formula, `:20` diagram, `:46-47` commands (add Task B's THOR seed step after `:47` if it is a separate command — Task B owns the exact line).

### `data/README.md`
- `:5` `every file is MD5-checked against docs/data-manifest.md` — already false for GADM, now also THOR (no source MD5): -> `pinned files are MD5-checked against docs/data-manifest.md (GADM/THOR publish no source checksum; local MD5s recorded there).`
- `:7` `thor/, osm/, imagery/ do not exist yet` -> `osm/, imagery/ do not exist yet`; update the date.
- `:13` `data/thor/        thor_data_vietnam.csv (manual data.world download, not yet present)`
  -> `data/thor/        THOR_Vietnam_7_31_2013.csv (2,627,971,171 B; manual data.world THOR_Vietnam.zip + 7-Zip extract, see manifest §4)`
- `:12` DB line: size/contents change after seeding -> `data/clearfield.db  seeded SQLite DB, <from Task B: bytes> (106 zones, 541,397 craters, strike_density on <from thor_scan.json> zones)`.

### Flagged, outside the three named docs (same stale fact, owners differ)
`frontend/index.html:6` + `frontend/README.md:5` ("needs THOR strike density and OSM"),
`pipelines/scoring.py:15,121` (runtime print "expected until THOR ... and OSM ... land"),
`scripts/seed_db.py:3,8-9`, `tests/test_api.py:63` (asserts first zone's
`strike_density is None` on a fixture DB — recheck if fixture becomes the real
seeded DB), `WORKFLOW_SYNTHESIS.md:534-538` (see §4). Task B should sweep
`grep -rn "THOR+OSM\|until THOR"`.

---

## 4. WORKFLOW_SYNTHESIS §5 THOR blockers (`:527-538`): close vs remain

Header `:527-528` `**THOR** (thor_data_vietnam.csv absent; manual data.world account, scripts/download_data.py:85, docs/getting-started.md:32):`
-> `**THOR** — RESOLVED <date>: THOR_Vietnam.zip manually downloaded, 7-Zip-extracted to data/thor/THOR_Vietnam_7_31_2013.csv, seeded by <Task B>; download stays manual (manifest §4).`

CLOSES (once extracted AND Task B seeds; extraction alone closes only #3):
1. `:530-531` in part — `zones.strike_density NULL 106/106` closes:
   non-NULL on `<from thor_scan.json>` zones (Task B decides 0.0 vs NULL for
   zero-mission zones — must be recorded, it changes §2.4 scorability).
   `agent/templates/en/survey-report.md:4` `{{ zone.strike_density }}`
   becomes fillable. BUT the clause "0 zones scorable, demo Moments 1-2
   impossible" does NOT close — see Remains #1.
2. `:532-533` Cambodia `demo_area` unblocked: pick `<from thor_scan.json>`
   top-density province, set `countries/cambodia.json:5`, flip
   `tests/test_profiles.py:15-18`. Closes only when that pick is committed.
3. `:534-538` fully closes: header seen (`TgtCountry`), values confirmed,
   single-string inexpressiveness fixed by the §1 list shape
   (`VIETNAM` -> `["SOUTH VIETNAM","NORTH VIETNAM"]`).

REMAINS (unchanged by THOR):
1. **OSM (`:540-548`) still independently blocks all ranking**: `zones.exposure`
   NULL 106/106 => per §2.4 still 0 scorable zones, demo Moments 1-2 still
   impossible. Plus §6-U9: no exposure formula pinned — data alone won't fix it.
   Also crater_evidence is non-NULL on only 9 zones (Barthelme coverage), a
   third independent cap on ranked zones even after OSM.
2. **META_API_KEY (`:507-525`)**: `/explain` 501, Spark stub, km/lo templates,
   cached demo responses, SAM (`sam_segment.py` + `tiling.py` + absent
   `data/imagery/`) — all untouched by THOR.
3. `:550-552` non-blockers stay absent: PostGIS, UXOTi_NPA/AMLID, Barthelme
   `data.zip`/`models.zip`, Sentinel-2/NICFI/KH-9 imagery.

Net: delete the THOR sub-block or mark RESOLVED; §5 title
"Blocked on META_API_KEY / THOR / OSM" -> "Blocked on META_API_KEY / OSM".
