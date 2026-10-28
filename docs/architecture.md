# Architecture

## Principle

One job per model. If two models could do it, the cheaper / local / deterministic one wins. The ranking math is plain code on purpose: it must be reproducible and auditable by demining professionals.

## Pipeline

```
Imagery + THOR ──► SAM 3.1 (local batch on RTX 3080, cached per chip) ──► masks
Masks + THOR + OSM ──► code + PostGIS ──► ranked zones + stored components
User question (EN/Lao/Khmer) ──► Muse Spark ──► query ──► map + explanation + report
Field photo + GPS + notes ──► Muse Glimmer (offline) ──► find record ──► syncs to PostGIS
```

## Components

### SAM 3.1 — the eyes (perception)
Segments disturbed earth in tiled imagery, prompted with text ("bomb crater", "circular depression", "disturbed earth"). Output: masks → GeoJSON polygons with area, circularity, confidence. Implemented (`pipelines/sam_segment.py`, Oct 28 2026): runs **locally** in `.venv-sam` (SAM 3 code from github.com/facebookresearch/sam3, torch cu128) on an RTX 3080 16 GB — Modal is not used. The checkpoint `facebook/sam3.1/sam3.1_multiplex.pt` is gated on Hugging Face and lives at `data/models/sam3.1/` (gitignored); without it the script records the exact failure in `summary.json` and exits — it never substitutes another model. (SAM 3.1 also exists on the Meta Model API as model `sam-3.1` via `api.meta.ai/v1/responses`; that route needs a Meta Model API key, is not wired, and the local route is primary.) Results are cached per (chip, prompt, threshold, checkpoint) under `data/imagery/sam/<scene_id>/cache/` — never re-run a cached chip. Must NOT decide risk, explain anything, or talk to users. A mask is evidence, not a verdict.

Resolution honesty (measured, Oct 28): at Sentinel-2 10 m/px a 5–15 m crater is ~1 pixel, so Sentinel-2 output is **disturbed-earth / crater-field patch candidates only** and must never be written as crater counts (`crater_evidence` is craters/km² from Barthelme). Individual-crater segmentation is only attempted on ~1–1.5 m/px imagery: KH-9 (Barthelme) and WorldStrat SPOT chips (1.5 m/px, CC BY-NC, 77 in-country chips, single-date 2013–2021 — a resolution benchmark, not zone evidence). The Barthelme KH-9 crater model (trained on Vietnam scenes, F1 0.61) is the baseline and validation set; its U-Net weights (`models.zip`, pinned in `scripts/download_data.py`) remain the preferred detector on KH-9 until SAM proves itself against those labels.

### Plain code + PostGIS — the scorekeeper (not a model, deliberately)
Fuses evidence into the priority score: THOR strike density × SAM crater evidence × proximity to villages / farmland / schools / roads (OSM), minus already-surveyed status. Same inputs → same score, every time. Models explain the score; they never invent it. Output: ranked priority zones with component numbers stored alongside, so Spark can cite them.

### Muse Spark — the brain & voice (HQ, cloud, Meta Model API)
1. **Query translation:** natural language in English, Lao, or Khmer → structured tool/SQL calls over PostGIS.
2. **Explanation:** turns a zone's stored score components into a plain-language "why is this zone ranked #3?" briefing, citing the actual numbers returned — never free-styling coordinates or counts.
3. **Reporting:** generates the survey report (EN + Lao + Khmer) from a template + the zone's structured facts.
Runs per query / per report via API. Cache responses; reserve roughly half the API credits for demo/submission runs. Must NOT segment imagery, run offline, or calculate the priority score.

### Muse Glimmer — the field hands (edge, offline)
Field triage with zero connectivity: photo of a find + GPS + spoken/typed notes (Lao) → one structured find record (object type, condition, estimated size, risk flag, location) in the *same schema* Spark/PostGIS use, so records sync into the same database back at HQ. Runs locally on an RTX 3080 16GB laptop via llama.cpp offload (Q4_K_M, 4K context, ~250-token JSON outputs) — an airplane-mode demo is the proof. Must NOT do heavy reasoning, ranking, or report polish — that's Spark, when connectivity exists.

### Muse Code — the builder (development only, never at runtime)
Writes the product: FastAPI + PostGIS schema, tiling pipeline, SAM wrapper, fusion scoring code, map UI, Spark agent wiring, Glimmer endpoint, tests.

### Muse Image — the face (submission only, never in the data path)
Hero image, explainer graphics, diagram polish for the submission page and demo video. Must NOT touch detection data — no synthetic "satellite imagery" as input, no generated craters presented as real. Anything it makes is labeled illustrative.

## Multi-country design

Country is a configuration, never code. See [`countries/README.md`](../countries/README.md). Portability tiers: Tier 1 Cambodia/Vietnam (same THOR file, same ordnance — cheapest proof); Tier 2 WWII Europe (same strike-data shape, re-validation needed); Tier 3 modern conflicts (UCDP/ACLED + UNOSAT, new validation required).

## Hard rules

- Never present model predictions or Muse Image output as real detection data.
- The system never instructs anyone to approach a suspected live item; ambiguous finds escalate to a human operator.
- Official hazard polygons (national IMSMA databases) are partnership-gated everywhere and are never a dependency — the system is built on public data only.
- If a step fails, record the exact failure rather than silently substituting a different dataset or model.
