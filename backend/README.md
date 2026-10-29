# backend/ — FastAPI app

Entry: `uv run uvicorn backend.app.main:app --port 8000` (serves the
GUI at `/`). Details: `../docs/getting-started.md` §4.

- `app/main.py` — routes: `/`, `/health`, `/countries`, `/zones`,
  `/finds` (POST), `/buildings/{country}` (binary point slices),
  `/explain` (POST, cache-first from `demo/cached-responses/`; 501 on
  cache miss until live Spark is wired).
- `app/profiles.py` — country profile loading/validation.
- `app/config.py` — env (`META_API_KEY`, `DATABASE_URL`, local DB path).
- `app/db.py` — SQLite connection helper.

Handlers are plain functions (tests call them directly, no sockets).
Missing DB is 503, cache miss without `META_API_KEY` is 501 — never
invented data. A `/explain` cache hit needs no API key.
