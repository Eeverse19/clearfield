# Finding bombs from aerial data — research synthesis (2026-10-28)

Five parallel research streams (crater-detection methods, UXO sensor
physics, mine-action doctrine, contamination modelling, Ukraine
operations). Full agent reports are in session history; this file keeps
the load-bearing numbers and the rules they impose on ClearField.

## The funnel is the product

Ukraine released 41,753 km2 by non-technical survey vs 171 km2 by
clearance (~244:1). Every operational system uses imagery to *cancel*
land cheaply and reserves clearance for the tail. ClearField's scoring
has this shape already; nothing below changes it.

## What detects what (measured, not claimed)

- **Craters, per-object:** dependable automation needs ~15-20 px across
  the crater. Duncan et al. (WorldView-2 0.5 m, Ukraine): F1 0.797 for
  craters >60 m2 (>17 px), F1 0.48 all sizes on independent regions.
  Lin et al. (WV-2, Cambodia): F1 0.79 at 6-24 px in one validation
  region. Barthelme (KH-9 1 m): per-object F1 0.64 Quang Tri (open)
  vs 0.44 tri-border (jungle/mountain); Group (merged) class ~0.
- **Below ~6 px: no per-object detection.** Sentinel-2 recovers ~51%
  of crater *area* (Skakun fusion), never counts. PlanetScope 3 m:
  ~63% of area. Our Sentinel-2 SAM layer is therefore disturbed-field
  area, as labelled — the literature agrees.
- **SAM has no published terrestrial crater benchmark.** Zero-shot SAM
  crater evidence is planetary and qualitative. SAM's defensible role:
  box-prompted mask refinement of detector/human candidates (Ren et
  al.: box prompts >> point prompts; up-sampling imagery helps SAM).
  Detector-first (U-Net), SAM-second is the stack the evidence supports.
- **UXO items themselves:** only UAV magnetometry (large ferrous items)
  and RGB (surface items) are past pilot stage. Laos' main threat,
  BLU-26 bomblets (64 mm, aluminium body), is undetectable from a
  flying magnetometer (~0.5 m max range vs >=1 m flight height).
  Thermal works to ~10 cm depth in bare soil at dawn/dusk transitions.
  Airborne GPR standalone is negative (14/45 in ideal conditions).
  LiDAR maps terrain under canopy; it does not detect bomblets.
- **Operational reality (HALO Ukraine):** 542 drone flights, 11 TB,
  analyst 3-5 days per minefield; AI field-validated Apr 2025 at an
  undefined "~70% accuracy". Vegetation collapses detection
  95% (low grass) -> 5% (trees/bushes) (Safe Pro's own model).

## Doctrine constraints (IMAS) on anything we output

- Bombing/strike records are **never direct evidence** (IMAS 08.10,
  TNMA 08.20/02). Model output can propose *candidate SHA* (indirect
  evidence) or *evidence points*; it cannot create a CHA, cancel,
  reduce, or clear land. Craters are listed as direct evidence of a
  detonation, not of remaining hazard — state the convention used.
- Single finds are **points** (EOD spot tasks), never polygons.
- Buffers must declare their type: record-error (Lin used 1,750 m
  diameter for B-52 payload coords), delivery footprint (B-52
  500x1,500 m; CBU-24 mean ~1.1 ha, up to 12 ha per target location),
  or CMRS fade-out (50 m from last find, inside a proven footprint).
  Cambodia BLS caps SHA polygons at 300,000 m2, split on natural
  features; CMRS polygons running >15% over at clearance are judged
  inaccurate — that is our feedback metric.
- Hazard classification stays separate from priority/impact scoring;
  low impact never downgrades a hazard (IMAS 07.11).

## Modelling rules for the dud-probability layer

- No validated strikes+craters -> P(live UXO) model exists. Build the
  generative version: strikes x bomblets/dispenser (CBU-24 = 665,
  sourced) x footprint kernel x dud scenario x survival, calibrated
  on held-out clearance finds (Negative Binomial on searched boxes).
- Dud rate is a **scenario set** (sourced: 2.35%-37%; Laos "30%" is a
  programme estimate, not a measurement). A global dud scalar cannot
  change zone ranking; only type/soil-varying rates can. In dense
  overlap (Xiangkhoang), report expected count lambda, not P(>=1)
  (s saturates).
- Crater density is a lower bound on bombs delivered, never a UXO
  estimator (bomblets leave no crater; airburst/removal/record error
  all break the subtraction). Lin's "44-50% unexploded" is
  unaccounted-bombs arithmetic — do not quote as a dud rate.
- Validation: spatial block hold-out (leave-one-village-out), near-
  hazard hard negatives (Desk-AId: F1 0.90 random -> 0.49-0.57 near
  hazards), CHA-expansion tracking vs the 15% trigger. No data /
  no search effort = "unknown", never "safe".

## Recommended stacks (from the methods review)

- **Heritage (Laos/Cambodia):** KH-9/CORONA at 1 m + Barthelme U-Net
  (detector-first), SAM box-refinement optional, THOR as prior.
  Expect F1 ~0.6 open, ~0.44 jungle. Elevation (LiDAR DTM where it
  exists) beats reflectance for old craters (Dolejs: Mask R-CNN
  F1 0.65 at 0.5 m/px DTM, under-canopy capable).
- **Modern (Ukraine):** Sentinel-1 coherence screening (free,
  monsoon-proof) -> PlanetScope anomaly area -> 0.5 m U-Net counts
  where tasked; UNOSAT points as labels; FIRMS as timing cue only.
- **Field (both):** drone RGB orthomosaic + analyst for surface
  evidence in open plots; magnetometry only for large ferrous items
  in flyable terrain; thermal dawn/dusk screening trials before any
  budget commitment. All aerial outputs are candidate lists for
  ground investigation — no sensor certifies absence.
