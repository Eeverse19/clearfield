# KH-9 bomb-crater coordinates (`data/kh9/bomb_coordinates.*`)

Generated 2026-10-28 by `scripts/kh9_match.py` from the seeded Barthelme
craters (`data/clearfield.db`, 541,397 rows) matched against the local
KH-9 frames (`data/kh9/`, Edinburgh DataShare 8 m/px). QA overlays:
`scripts/kh9_qa_overlays.py` -> `data/kh9/qa/` (6 windows + sidecars).

## What it is

One row per crater with every coordinate form a user or a model needs:

- `lon`, `lat` (EPSG:4326) and `utm_easting`, `utm_northing` (EPSG:32648)
- `kh9_frame` + `kh9_area`: the photo it was seen in (first frame, by
  area/filename, whose valid pixels contain the centroid)
- `pixel_col_8mpp`, `pixel_row_8mpp`: fractional pixel in that 8 m/px frame
- `pixel_col_1mpp_derived`, `pixel_row_1mpp_derived`: x8 (the 1 m/px
  frames share the extent; not read locally, `derived_1mpp=true`)
- `area_m2`, `circularity`, `crater_class` (Barthelme classes 1-5),
  `all_frames` (overlapping frames), `frame_pixel_valid`

Result: 541,397/541,397 craters in a frame; **541,375 (99.996%) assigned
to a frame where the centroid pixel is on valid imagery** (the frames are
diagonal strips; bounds-only assignment put 23.6% on nodata corners).
Per country: Vietnam 511,541; Laos 24,197; Cambodia 5,659.
Outputs: `bomb_coordinates.csv.gz` (38 MB), `bomb_coordinates.geojson`
(349 MB, in-frame subset = all), `kh9_match_summary.json`.

## What it is not

These are **bomb-impact crater locations predicted by the Barthelme
U-Net in 1972-73 KH-9 photos**, not confirmed unexploded ordnance, and
not present-day ground truth. Source confidence is NULL in the original
predictions; none is invented here. Geolocation error of the source
orthorectification is ~7 m (Quang Tri) / ~17.5 m (tri-border): fine for
zone density and window-level photo evidence, not for rim-level claims
against other sensors. At 8 m/px the median crater (~8.7 m) is ~1 px;
crater *shape* is visible only at 1 m/px.

## Verification done

- DB centroid round-trip: first DB crater back-transforms exactly to the
  first feature of `predictions/quang_tri/crater_centroids.geojson`
  (no axis swap, no seeding shift).
- Visual QA (`data/kh9/qa/`): in the densest Quang Tri window (34,876
  craters / 64 km2) markers blanket disturbed ground and leave river
  channels empty; same pattern in tri-border windows. Registration is
  consistent at window/density level.
- Alignment audit: all 10 frames EPSG:32648, 8.0 m/px, north-up; valid
  imagery is a diagonal strip per frame (4-77% of bbox).

## Producing coordinates for new areas (e.g. Xiangkhoang)

The detector is not the bottleneck — and is now verified locally:
`scripts/barthelme_reproduce.py` (in `.venv-unet`) reproduced the
authors' test-split scores on 2026-10-30: Quang Tri per-object F1
0.639 (published 0.64; P 0.685/R 0.599), pixel F1 0.654 (0.65);
tri-border F1 0.439 (0.44), pixel 0.407 (0.41). Weights in
`data/barthelme/models.zip` are whole pickles that load with
`segmentation-models-pytorch==0.3.3`
(installed with `--no-deps`; a plain install breaks the SAM env's timm).
Recipe: 256x256 tiles at 1 m/px, per-tile min-max scaling, argmax over
7 classes, class 6->0, remove <25 px objects/holes, majority-class
components, polygonize, centroid, EPSG:4326 (full detail in the
2026-10-28 U-Net reproducibility analysis; reproduction targets:
Quang Tri crater F1 0.64, tri-border 0.44 from `tables.zip`).

The bottleneck is imagery: a new province needs 1 m/px orthorectified
KH-9. Raw Declass 3 frames come from USGS EarthExplorer (free account),
then NASA Ames Stereo Pipeline orthorectification with GCPs + DEM
(1-3 days/frame), plus 50-100 hand-labelled tiles to validate transfer
before trusting counts (expect F1 at or below tri-border's 0.44 until
then). EarthExplorer frame search for Xiangkhoang/Tbong Khmum is the
next manual step; SpaceFromSpace's 946-scene footprint catalog covers
neither province (checked 2026-10-28).
