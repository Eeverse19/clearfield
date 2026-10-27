# Frontend

Single-file map GUI (`index.html`, no build step, no external dependencies —
the map is drawn on a canvas from the zone geometry the API already serves).

## Run it

Easiest: double-click **`Start-ClearField.bat`** in the repo root. It starts
the server and opens the map in your browser.

Or manually:

```powershell
uv run uvicorn backend.app.main:app --port 8000
# then open http://localhost:8000/
```

The backend serves this page at `/`, so no separate static server (and no
CORS setup) is needed. Needs the seeded local DB (`data/clearfield.db`);
see `docs/getting-started.md`.

## What it does

- Choropleth map of all zones for Laos / Cambodia / Vietnam, switchable by
  score component: exposure (OSM), crater evidence, strike density, priority
  score. Grey means **no data**, which is deliberately different from zero.
- Evidence-ranking list (clearly labelled a preview while THOR strike
  density is unseeded — no zone is officially rankable yet), province
  search, surveyed-status filter, pan/zoom, demo-province shortcuts.
- Per-zone inspector: the three stored score components with percentiles,
  an honest rankability verdict, and a plain-language briefing generated
  locally from the real stored numbers (the Spark `/explain` agent is not
  wired yet; the button shows its real 501 response).
- Field-find recording against `POST /finds`, including click-on-map
  location capture and an offline queue in `localStorage` that syncs when
  the API is reachable (mirrors the offline-triage design in
  `docs/architecture.md`).
