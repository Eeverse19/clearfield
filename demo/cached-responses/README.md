# Cached demo responses

The demo must survive an API outage: `POST /explain` reads this directory
first and only falls through on a cache miss (501 until live Spark is
wired; a cache hit needs no `META_API_KEY`).

## Frozen `/explain` format

One JSON file per (zone, language), UTF-8, named exactly
`explain-<ZONE_ID>-<lang>.json` (e.g. `explain-LAO.17_1-en.json`), where
`<ZONE_ID>` is the GADM GID_1 (`zones.id`) and `<lang>` is one of
`en`, `lo`, `km`, `vi`. (The earlier `<moment>-<step>-<lang>.json`
placeholder grammar is retired for `/explain` — it cannot map a zone id
to a file. Non-`/explain` scripted steps in `docs/demo-script.md`
— Moments 0, 1, 3, 4 — still have no cached files.)

Each file is an object with exactly these fields:

```json
{
  "schema_version": 1,
  "kind": "explain",
  "zone_id": "LAO.17_1",
  "country": "laos",
  "admin_name": "Xékong",
  "lang": "en",
  "explanation": "<frozen template text, see below>",
  "score_components": {
    "strike_density": 10.358717913055413,
    "crater_evidence": 0.028808749735117645,
    "exposure": 4.9913250837752585,
    "surveyed_status": "unsurveyed",
    "priority_score": 0.013058051643634173,
    "priority_rank": 3,
    "scored_at": "2026-10-28T18:22:41.166149+00:00"
  },
  "origin": "template_from_stored_components",
  "generated_from": "stored score components only (pipelines/scoring.py); no live model"
}
```

Rules enforced by the `/explain` loader (`backend/app/main.py`):

- **Origin is a deterministic template, not a model output.** The English
  `explanation` must equal `render_explanation()` over the current DB row
  (stored values only, formatted `.6g`; exact values stay checkable in
  `score_components`). Nothing here is hand-written to look like a model
  output, and hand-edited text is rejected (503), never served.
- **Stale = miss.** If `score_components` no longer exactly matches the
  DB row, the file is treated as absent (501 on miss), never served.
- **Malformed = 503.** Bad JSON, wrong schema/fields/types, or a
  zone/country/name/language mismatch is a server data fault.
- **English only, honestly labeled.** Only `en` files are seeded. A
  `lo`/`km`/`vi` request for a seeded zone serves the English file with
  `lang: "en"` and `requested_lang` echoing the request, so clients can
  label the fallback. Real `lo`/`km` files need a translation source the
  repo does not have yet (see TASKS.md P1-4/P1-5).

## Regenerating

After every `pipelines/scoring.py` run (and after any zone rename):

```
uv run python scripts/make_cached_explanations.py
```

The generator reads `data/clearfield.db` read-only, seeds one `en` file
per ranked zone, and refuses to write anything if a ranked zone has a
NULL score component. Currently seeded: the 6 ranked zones
(`KHM.20_1`, `KHM.22_1`, `LAO.1_1`, `LAO.4_1`, `LAO.17_1`, `LAO.12_1`).
`tests/test_cached_explanations.py` fails if these files drift from the DB.
