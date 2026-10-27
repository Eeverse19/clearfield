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
  (144,672 assigned rows mismatch it).
- Manifest mission claims are all low; the observed counts in the final
  spec replace them.

Status: spec complete, **not yet implemented** — `strike_density` is still
NULL on 106/106 zones, so scoring still scores 0. See `../../TASKS.md` P0-1.
