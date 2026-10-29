# backend/ — FastAPI app

Entry: `uv run uvicorn backend.app.main:app --port 8000` (serves the
GUI at `/`). Details: `../docs/getting-started.md` §4.

- `app/main.py` — routes: `/`, `/health`, `/countries`, `/zones`,
  `/finds` (POST), `/buildings/{country}` (binary point slices),
  `/explain` (501 until Spark is wired; by design).
- `app/profiles.py` — country profile loading/validation.
- `app/config.py` — env (`META_API_KEY`, `DATABASE_URL`, local DB path).
- `app/db.py` — SQLite connection helper.

Handlers are plain functions (tests call them directly, no sockets).
Missing DB is 503, missing API key is 501 — never invented data.
