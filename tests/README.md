# tests/ — pytest suite

Run: `uv run pytest` (on this OneDrive checkout set
`UV_LINK_MODE=copy` first). Handlers are called directly — no
TestClient sockets (sandbox restriction, see `test_api.py` header).

Per-area: `test_api.py` (endpoints + GUI hooks), `test_scoring.py`,
`test_osm_exposure.py`, `test_building_exposure.py`,
`test_seed_db.py` / `test_seed_thor.py` (seed regressions),
`test_sentinel2_catalog.py`, `test_tiling_sam.py`,
`test_worldstrat.py`, `test_profiles.py`, `test_local_schema.py`.

State-dependent smoke tests skip or fail honestly when machine-local
data (seeded DB, THOR CSV) is absent — that is signal, not noise.
