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

- Choropleth map of all zones for Laos / Cambodia / Vietnam with five
  layers. **Official priority** (the default) paints only zones with a
  stored `priority_rank` amber with their `#n` rank numeral; every other
  zone is hatched "not enough data to rank". **Strike records (THOR)** and
  **Exposure (OSM)** use fixed raw classes that are identical on every
  country tab (so shades are comparable across countries); **Crater
  evidence** uses four classes scaled within each country (crater values
  are not compared across countries today). **Data coverage** colors each
  zone by exactly which of the three score components are missing.
  Hatched grey always means **no data** — never zero, never low, never
  safe. Strike density is historical THOR mission records (recorded
  intended targets, not verified impacts), labelled as records/evidence,
  never as present-day danger.
- Rankability list: an **Official priority** group (zones with all three
  score components — 6 ranked today: Laos 4/18, Cambodia 2/25, Vietnam
  0/63) followed by one group per missing-data reason. Ordering inside a
  not-rankable group is an evidence preview only, never an official rank
  or a clearance order. Province search, surveyed-status filter,
  pan/zoom, and demo-province shortcuts are included.
- Per-zone inspector: the three stored score components as raw values
  plus their per-country scoring normalization
  (`log(1+x)/log(1+country max)`, the same formula
  `pipelines/scoring.py` uses) with an explicit product line for ranked
  zones — score and rank shown are the stored values, never recomputed
  into a new score. Missing components show a hatched "missing — blocks
  the score" track; unscorable zones say exactly which component is
  missing and are never scored as 0. A plain-language briefing is
  generated locally from the real stored numbers (the Spark `/explain`
  agent is not wired yet; the button shows its real 501 response).
  Exposure is credited "(c) OpenStreetMap contributors" (ODbL 1.0)
  wherever scores are shown; Vietnam has no OSM extract yet, so its
  Exposure layer is disabled rather than shown as zero.
- Field-find recording against `POST /finds`, including click-on-map
  location capture and an offline queue in `localStorage` that syncs when
  the API is reachable (mirrors the offline-triage design in
  `docs/architecture.md`).
