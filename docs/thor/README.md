# THOR strike-density specs (rescued 2026-10-27)

These files were living in `.uv-tmp/` (gitignored, one `uv` cache clean away
from deletion). They were **copied** here — the originals still exist in
`.uv-tmp/` and can be deleted once this copy is committed.

| File | What it is |
|---|---|
| `thor_final_spec.md` | **Start here.** Final merged, parent-ready implementation spec for `zones.strike_density`. Supersedes conflicting parts of the two specs below. |
| `thor_seed_spec.md` | Task B: exact `scripts/seed_thor.py` spec (shape/API). Its CSV-rename step is superseded by the final spec §1. |
| `thor_doc_edits.md` | Task C: exact old→new edits for `countries/*.json`, README, manifest (filename + `country_filter` string→list). |
| `thor_scan.json` | Task A: full-scan evidence over the real CSV (row/coordinate/zone counts). |
| `thor_scan.py`, `thor_crosscheck.py`, `fix_false_zeros.py` | The one-off scanners that produced the evidence above. Kept for provenance; not part of the runtime. |

Key resolved decisions (final spec §0–1):

- Canonical CSV: `data/thor/THOR_Vietnam_7_31_2013.csv` (2,627,971,171 B,
  md5 `939f28d770d9b3b9acd37553eab0fb85`). Profiles change to this name —
  **no file rename**.
- Point-in-zone is authoritative; `TgtCountry` is cross-check only
  (144,672 Task-A first-hit scan; 144,697 baseline-A under §2.4 smallest-id; corrected C mismatch 144,468).
- Manifest mission claims are all low; the observed counts in the final
  spec replace them.

Status (2026-10-28): **implemented + real run DONE 2026-10-28.** `scripts/seed_thor.py`
(+ `.ps1`/`.sh` wrappers, `tests/test_seed_thor.py`, profile edits) landed
per the final spec incl. the §9 corrected-seed rules (forced EPSG:1542
Indian-1960→WGS84 datum transform; SACCOACT dedup from 1971-04-01; weapon
filter **not** applied — U17 missions/km² stands; D1–D4 confirmed by owner
2026-10-28 as pinned defaults, spec §9.6). Corrected (C) real-run summary:
rows 4,670,422; assigned 3,401,836 (cambodia 191,184 / laos 1,090,845 /
vietnam 2,119,807); invalid 1,130,146; outside 108,385;
deduped_saccoact 30,055; corrected mismatch 144,468. `strike_density`
is non-NULL on 106/106 zones and scoring ranks Laos 4/18, Cambodia 2/25,
Vietnam 0/63. See `../../TASKS.md` P0-1.

History (dry-run gate, kept as history): the earlier 2026-10-28
`--dry-run` reproduced the baseline-A scan expectation (rows_read
4,670,422 / invalid_coords 1,130,146 / baseline_assigned 3,419,286)
exactly, then stopped at the baseline-A gate over 27 boundary missions
— the seed follows the §2.4 smallest-`zones.id` tie-break while the
pinned constants encode the Task A scan's first-hit order. That gate
was resolved before the real run above; baseline-A figures are scan
expectations, not seeded facts.
