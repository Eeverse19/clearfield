# scripts/ — data acquisition and utilities

Everything here reproduces something under `data/` (gitignored) or
supports the pipelines. Sources/checksums: `../docs/data-manifest.md`.

- Downloads: `download_data.py` (Barthelme/GADM/OSM, MD5-pinned),
  `download_worldstrat.py` (WorldStrat HR chips), `download_kh9.py`
  (Edinburgh KH-9 frames), `download_oam.py` (OpenAerialMap pockets).
- Catalogs: `sentinel2_catalog.py` (630k Sentinel-2 scenes, STAC),
  `make_building_points.py` (footprint centroids for the GUI).
- Seeding: `seed_db.py` (zones + Barthelme craters), `seed_thor.py`
  (strike density; needs the manual THOR CSV in `data/thor/`).
- KH-9: `kh9_match.py` (crater -> photo-frame coordinates),
  `kh9_qa_overlays.py` (visual QA windows).
- Utilities: `dashboard.py` (live monitor, 127.0.0.1:8765),
  `filemap.py` (regenerates the map in `../INDEX.md`).

Wrappers (`.ps1`/`.sh`) are thin shells over the `.py` files.
