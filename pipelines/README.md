# pipelines/ — zone-column pipelines

Each pipeline owns exactly one output and never touches scores except
`scoring.py`. Run order and commands: `../docs/getting-started.md` §5.

- `scoring.py` — deterministic priority score from the three components.
- `osm_exposure.py` — OSM features/km2 -> `zones.exposure`.
- `building_exposure.py` — Microsoft footprints/km2 -> `zones.building_density` (auxiliary, not scored yet).
- `tiling.py` — Sentinel-2 L2A scene -> georeferenced chips (for SAM).
- `sam_segment.py` — SAM 3.1 chips -> mask GeoJSON (local `.venv-sam`; needs the gated checkpoint in `data/models/sam3.1/`).
- `_profile.py` — shared `--country` handling.
