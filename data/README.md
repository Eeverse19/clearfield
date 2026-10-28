# data/ (never committed)

Nothing under here except this file and `.gitkeep` is committed to git.
`scripts/download_data.sh` / `scripts/download_data.ps1` reproduce this folder
from public sources; pinned files are MD5-checked against
`docs/data-manifest.md` (GADM/THOR publish no source checksum; local MD5s
recorded there).

Actual layout (Oct 28, 2026):

```
data/barthelme/   README.txt, tables.zip, predictions.zip (data.zip/models.zip not fetched)
data/gadm/        gadm41_{LAO,KHM,VNM}_1.json, gadm41_{LAO,KHM,UKR}_0.json
data/clearfield.db  seeded SQLite DB, 825,843,712 B (106 zones, 541,397 craters; strike_density on 106/106 (corrected C seed, 2026-10-28); exposure 43/106: Laos 18 + Cambodia 25, Vietnam 0; crater_evidence 9/106; ranked 6: Laos 4/18, Cambodia 2/25, Vietnam 0/63)
data/thor/        THOR_Vietnam_7_31_2013.csv (2,627,971,171 B; manual data.world THOR_Vietnam.zip + 7-Zip extract, see manifest section 4)
data/osm/         laos-261025.osm.pbf, cambodia-261025.osm.pbf (Geofabrik, pinned; vietnam not acquired)
data/sentinel2/   NOT ON DISK (verified 2026-10-28) — the 630,318-scene catalog claimed in the Oct 28 addendum is absent; regeneration pending
data/worldstrat/  NOT ON DISK (verified 2026-10-28) — the 77 HR chips claimed in the Oct 28 addendum are absent; regeneration pending
data/models/      sam3.1/sam3.1_multiplex.pt (gated checkpoint; not yet present)
data/imagery/     NOT ON DISK (verified 2026-10-28) — the 191-chip Xiangkhoang tiling output claimed in the Oct 28 addendum is absent; regeneration pending
```
