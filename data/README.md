# data/ (never committed)

Nothing under here except this file and `.gitkeep` is committed to git.
`scripts/download_data.sh` / `scripts/download_data.ps1` reproduce this folder
from public sources; every file is MD5-checked against `docs/data-manifest.md`.

Actual layout (Oct 28, 2026):

```
data/barthelme/   README.txt, tables.zip, predictions.zip (data.zip/models.zip not fetched)
data/gadm/        gadm41_{LAO,KHM,VNM}_1.json, gadm41_{LAO,KHM,UKR}_0.json
data/clearfield.db  seeded SQLite DB, 825,741,312 B (106 zones, 541,397 craters)
data/thor/        thor_data_vietnam.csv (manual data.world download, not yet present)
data/osm/         laos-261025.osm.pbf, cambodia-261025.osm.pbf (Geofabrik, pinned; vietnam not acquired)
data/sentinel2/   catalog/ (630,318-scene STAC catalog, done) + catalog_run*.log
data/worldstrat/  77 HR 1.5 m/px chips (download/extract in progress) + metadata.csv, index.csv
data/models/      sam3.1/sam3.1_multiplex.pt (gated checkpoint; not yet present)
data/imagery/     tiles/S2B_48QUG_20260112_0_L2A/ (191 chips + manifest), sam/ (SAM output, pending)
```
