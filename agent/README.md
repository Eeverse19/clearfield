# Spark agent (HQ, cloud)

Muse Spark does three jobs, per `docs/architecture.md`:

1. Query translation: EN/Lao/Khmer question -> structured query over the DB.
2. Explanation: a zone's stored score components -> plain-language briefing
   citing the actual numbers. Never invents coordinates, counts, or scores.
3. Reporting: survey report from `templates/<lang>/` + the zone's facts.

Rules: cache-first (`demo/cached-responses/` is read before any live call, so
the demo survives an API outage); never calculate the priority score; never
segment imagery. Needs `META_API_KEY` in `.env` — not yet provided, so
`spark.py` is a stub that refuses to run without it.
