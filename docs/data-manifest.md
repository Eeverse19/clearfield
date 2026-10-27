# Data manifest

Every file below is public. Nothing under `data/` is committed to git; `scripts/download_data.py` (via the `.sh`/`.ps1` wrappers) reproduces the pinned files, and Barthelme MD5s are checked on download. Checksums marked ✓ were verified against the source-published value (Oct 22, 2026); GADM publishes no checksum, so its MD5s below are locally computed (Oct 26, 2026), not source-verified.

## 1. Barthelme KH-9 crater pack ⭐ (primary)

- Source: Zenodo record 10629987 (doi 10.5281/zenodo.10629987). Code (MIT): github.com/pbarthelme/detecting-vietnam-war-bomb-craters
- Study areas: `quang_tri`, `tri_border_area` (tri-border includes Laos)
- `data.zip` (1,853,764,395 B) — md5 `ee8860cacf709c5d1d91d0c5ff88b2bd` ✓
  - `data/0_data_processing/<area>/tiles/` — 256×256 GeoTIFF tiles
  - `data/1_crater_labels/<area>/labels.geojson` — hand-labeled crater polygons
  - `data/2_training_data/<area>/data.h5` + combined `data.h5` — train/val/test splits
- `models.zip` (972,209,531 B) — md5 `5afc0bacbd753099e12b48a38f6c3652` ✓ — `models/<area>/model.pth` final UNet per area + `models/cv/*/model.pth` variants
- `predictions.zip` (47,886,932 B) — md5 `c79cd869f7d5bb7bfc0e976c0ff7c783` ✓ — `predictions/<area>/crater_polygons.geojson` + `crater_centroids.geojson`; exactly 541,398 polygon features (quang_tri 442,157 + tri_border_area 99,241), EPSG:32648, class in `properties.value` (1–5), no per-crater confidence. Downloaded + seeded Oct 26, 2026: 541,397 craters in `data/clearfield.db` (1 skipped)
- `tables.zip` (2,516 B) — md5 `fd4f9e034fe4531554a21f89c39f3cb0` ✓ — per-area `pixel_eval.csv`, `crater_eval.csv`, `correlations_thor_craters.csv`
- `README.txt` (3,987 B) — md5 `44faf252bc8daa32d55d80c4ed668ba7` ✓
- Label classes: 0 Background, 1 Pattern, 2 Rim, 3 Group, 4 Crescent, 5 Bowl, 6 Boundary (0 and 6 in training data only). Reported F1 0.61.

## 2. UXOTi_NPA (supplementary)

- Source: Figshare article 21688673, file 38466134 (via github.com/MilanBajicjr/UXOTi_NPA) — 808 UAV thermal images of real UXO, Norwegian People's Aid, Bosnia
- `UXOTi_NPA_1_class.zip` (506,039,055 B) — md5 `46f14783e8c1ee7724d9ebfa02b2a686` ✓ — CVAT bounding-box annotations, 1-class version

## 3. AMLID (supplementary)

- Source: Zenodo record 18001447 (doi 10.5281/zenodo.18001447), CC BY 4.0 — 12,078 drone RGB+LWIR landmine images, Pascal VOC XML boxes, 4 grouped classes
- `landmine_final.7z` (2,023,555,007 B) — md5 `2d24d2acc7e67bf55d48a5f5c5d508fb` ✓

## 4. Strike / conflict records

- **THOR, Vietnam War** — data.world/datamil/vietnam-war-thor-data, file `thor_data_vietnam.csv` (~1.5 GB). Free data.world account required. Missions with coordinates: Laos 1,041,519; South Vietnam 1,620,422; North Vietnam 581,897; Cambodia 144,944; Thailand 2,427. Records targets, not impacts.
- **UCDP GED** — ucdp.uu.se/downloads, free, no registration, CC BY 4.0 (modern conflicts)
- **ACLED** — acleddata.com, free myACLED account (modern conflicts, near-real-time)

## 5. Imagery, boundaries, geography

- **KH-9/CORONA raw scans** — USGS EarthExplorer, Declassified Data > Declass 3, free USGS account
- **Georeferenced KH-9** — Edinburgh DataShare: Quang Tri doi 10.7488/ds/7682, tri-border doi 10.7488/ds/7683 (8mpp versions ~430 MB each)
- **Current imagery** — Sentinel-2, Planet NICFI tropics mosaics
- **Boundaries** — GADM 4.1 admin-1 GeoJSON (geodata.ucdavis.edu/gadm/gadm4.1/json/), no source checksum; downloaded Oct 26, 2026: `gadm41_LAO_1.json` (183,636 B, 18 features, local md5 `7c58682405ad7e7cb08906e645c79e00`), `gadm41_KHM_1.json` (263,580 B, 25 features, local md5 `d830c8d34355eee27c0d08ce75de5923`), `gadm41_VNM_1.json` (821,030 B, 63 features, local md5 `831f106f2deffbeea6f978464816169c`)
- **Human geography (OSM exposure)** — OpenStreetMap country extracts via Geofabrik (`download.geofabrik.de/asia/`), snapshot/replication timestamp 2026-10-25T21:21:21Z (`261025` in filenames), written by `osmium/1.16.0` (OSMHeader). License: ODbL 1.0, © OpenStreetMap contributors — attribution required; the derived per-zone `exposure` density is a produced aggregate of this database, so keep this attribution wherever scores are shown. Pinned + verified Oct 27, 2026 (local MD5s identical to Geofabrik's published `.md5`; the `.osm.pbf` URLs below are the siblings of those `.md5` files — dated Geofabrik files may rotate, so re-pin rather than skip the checksum if a fetch 404s):
  - `data/osm/laos-261025.osm.pbf` (53,978,663 B) — md5 `bf854b5f14bec74d8854742d227b8695` ✓ — `https://download.geofabrik.de/asia/laos-261025.osm.pbf`
  - `data/osm/cambodia-261025.osm.pbf` (41,150,119 B) — md5 `7403c81f9de80c012fb930c0758e48ef` ✓ — `https://download.geofabrik.de/asia/cambodia-261025.osm.pbf`
  - No Vietnam extract acquired (out of demo scope): its 63 zones keep `exposure = NULL`.
  - Consumed by `pipelines/osm_exposure.py`: exposure = exposure features per km² (buildings as settlement proxy, settlement `place`, schools, highways, farmland/residential `landuse`; equal weight, one per OSM element; see module docstring for the v1 limits).
- **Elevation/canopy covariates** — Copernicus DEM, GEDI canopy height

## 6. Labeled damage data (modern conflicts)

- **UNOSAT damage assessments** — unosat.org/products, mirrored on data.humdata.org. Per-city/per-event GIS data, classes: destroyed / severe / moderate / possible. No bulk file; collect per area of interest.

## Not available (by design)

Official hazard-area polygons (national IMSMA databases: Laos NRA, Cambodia CMAA, etc.) are behind operator accreditation everywhere. ClearField never depends on them; published province-level statistics are used instead.
