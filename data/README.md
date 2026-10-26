# data/ (never committed)

Nothing under here except this file and `.gitkeep` is committed to git.
`scripts/download_data.sh` / `scripts/download_data.ps1` reproduce this folder
from public sources; every file is MD5-checked against `docs/data-manifest.md`.

Actual layout (Oct 26, 2026); `thor/`, `osm/`, `imagery/` do not exist yet:

```
data/barthelme/   README.txt, tables.zip, predictions.zip (data.zip/models.zip not fetched)
data/gadm/        gadm41_{LAO,KHM,VNM}_1.json
data/clearfield.db  seeded SQLite DB, 825,741,312 B (106 zones, 541,397 craters)
data/thor/        thor_data_vietnam.csv (manual data.world download, not yet present)
data/osm/         OSM extracts per country (URLs not pinned yet)
data/imagery/     Sentinel-2 / NICFI / georeferenced KH-9 (not yet present)
```
