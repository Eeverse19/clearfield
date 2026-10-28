"""SAM 3.1 text-prompted segmentation of tiling chips -> GeoJSON (pilot).

SAM sees only: it segments, it must not decide risk or explain anything
(docs/architecture.md). Input is a tiling manifest
(data/imagery/tiles/<scene_id>/manifest.json from pipelines/tiling.py);
output per scene is data/imagery/sam/<scene_id>/detections.geojson +
summary.json. Every mask becomes a polygon with area, equivalent
diameter, circularity and the SAM score. At Sentinel-2 10 m/px these are
disturbed-earth / crater-field *patch* candidates, never verified
individual craters; masks below --min-area-px are dropped as
unresolvable noise. Nothing here writes zones.crater_evidence.

Model: SAM 3.1 image model (facebook/sam3.1 checkpoint
``sam3.1_multiplex.pt``, code github.com/facebookresearch/sam3). The
checkpoint is gated: request access at
https://huggingface.co/facebook/sam3.1 and ``hf auth login`` first.
Without it this script records the exact failure in summary.json
(status="failed", stage="checkpoint_load") and exits 2 -- it never
substitutes another model or fabricates detections.

Local env (RTX 3080 16 GB is enough for 1008 px image inference):
  py -3.12 -m venv .venv-sam
  .venv-sam\\Scripts\\python.exe -m pip install torch==2.10.0 torchvision --index-url https://download.pytorch.org/whl/cu128
  .venv-sam\\Scripts\\python.exe -m pip install rasterio shapely pillow numpy
  .venv-sam\\Scripts\\python.exe -m pip install git+https://github.com/facebookresearch/sam3.git
  .venv-sam\\Scripts\\python.exe -m pip install einops triton-windows pycocotools psutil
  (einops/triton/pycocotools/psutil are unconditional imports in sam3 that
  its base install misses on Windows; rasterio works despite pip's
  numpy>=2 warning against sam3's numpy<2 pin -- verified 2026-10-27.)

Caching: each (chip, prompt, threshold, min-area, checkpoint) result is
stored under <out>/cache/<key>.geojson and never recomputed; if every
chip is cached the model is not even loaded. Delete a cache file to
redo that chip. Runs are resumable chip by chip.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `python pipelines/sam_segment.py`

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_REPO = "facebook/sam3.1"
CHECKPOINT_FILE = "sam3.1_multiplex.pt"
ACCESS_URL = "https://huggingface.co/facebook/sam3.1"
DEFAULT_PROMPTS = ("bomb crater", "circular depression", "disturbed earth")


def cache_key(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def mask_stats(geom) -> dict:
    """Area / diameter / circularity of a shapely geom in a metre CRS."""
    area = float(geom.area)
    perim = float(geom.length)
    return {
        "area_m2": round(area, 1),
        "equiv_diameter_m": round((4 * area / 3.141592653589793) ** 0.5, 1),
        "circularity": round(4 * 3.141592653589793 * area / perim**2, 3) if perim else 0.0,
    }


def dedupe(features: list[dict], iou_threshold: float = 0.5) -> list[dict]:
    """Drop lower-scored duplicates (same prompt, IoU > threshold).

    ``features`` carry a shapely geom under ``_geom`` and a ``score`` in
    ``properties``; chip overlaps make the same patch appear twice.
    """
    kept: list[dict] = []
    for f in sorted(features, key=lambda x: -x["properties"]["score"]):
        dup = False
        for k in kept:
            if k["properties"]["prompt"] != f["properties"]["prompt"]:
                continue
            inter = k["_geom"].intersection(f["_geom"]).area
            union = k["_geom"].union(f["_geom"]).area
            if union and inter / union > iou_threshold:
                dup = True
                break
        if not dup:
            kept.append(f)
    return kept


def masks_to_features(masks, scores, transform: dict, crs: str,
                      base: dict, min_area_px: int) -> list[dict]:
    """Polygonize boolean masks (list of 2D arrays) into GeoJSON-ready dicts."""
    import numpy as np
    from rasterio.features import shapes as raster_shapes
    from rasterio.transform import Affine
    from shapely.geometry import shape

    affine = Affine(transform["a"], transform["b"], transform["c"],
                    transform["d"], transform["e"], transform["f"])
    px_area = abs(affine.a * affine.e - affine.b * affine.d)
    out = []
    for mask, score in zip(masks, scores):
        m = np.asarray(mask).squeeze()
        if m.dtype != bool:
            m = m > 0
        if int(m.sum()) < min_area_px:
            continue
        for geom, _ in raster_shapes(m.astype("uint8"), mask=m, transform=affine):
            g = shape(geom)
            props = {**base, "score": round(float(score), 4),
                     **mask_stats(g), "area_px": round(float(g.area / px_area), 1)}
            out.append({"type": "Feature", "geometry": geom,
                        "properties": props, "_geom": g})
    return out


class CheckpointUnavailable(RuntimeError):
    pass


def load_processor(checkpoint: str | None, device: str, threshold: float):
    """Build Sam3Processor on the SAM 3.1 image checkpoint (gated download)."""
    try:
        from sam3.model_builder import build_sam3_image_model, download_ckpt_from_hf
        from sam3.model.sam3_image_processor import Sam3Processor

        ckpt = checkpoint or download_ckpt_from_hf(version="sam3.1")
        model = build_sam3_image_model(
            checkpoint_path=str(ckpt), load_from_HF=False, device=device)
        return Sam3Processor(model, device=device, confidence_threshold=threshold), str(ckpt)
    except Exception as e:
        raise CheckpointUnavailable(
            f"{type(e).__name__}: {e} | checkpoint {CHECKPOINT_REPO}/{CHECKPOINT_FILE} "
            f"is gated: request access at {ACCESS_URL}, run `hf auth login`, retry. "
            "No substitute model was used and no detections were produced.") from e


def run_chip(processor, chip_path: Path, prompts, threshold: float) -> dict[str, list]:
    """{prompt: (masks as numpy list, scores list)} for one chip image."""
    import numpy as np
    from PIL import Image

    image = Image.open(chip_path).convert("RGB")
    state = processor.set_image(image)
    results = {}
    for prompt in prompts:
        out = processor.set_text_prompt(state=state, prompt=prompt)
        masks = out["masks"].detach().cpu().numpy() if hasattr(out["masks"], "detach") \
            else np.asarray(out["masks"])
        scores = out["scores"].detach().cpu().numpy() if hasattr(out["scores"], "detach") \
            else np.asarray(out["scores"])
        results[prompt] = ([masks[i] for i in range(len(scores))],
                           [float(s) for s in scores])
        processor.reset_all_prompts(state)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--country", required=True, help="country profile id, e.g. laos")
    ap.add_argument("--manifest", type=Path, required=True,
                    help="data/imagery/tiles/<scene_id>/manifest.json")
    ap.add_argument("--prompts", nargs="+", default=list(DEFAULT_PROMPTS))
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--min-area-px", type=int, default=5,
                    help="drop masks smaller than this (5 px = 500 m2 at 10 m/px)")
    ap.add_argument("--checkpoint", help="local .pt path (default: download facebook/sam3.1)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--limit", type=int, help="only the first N chips (smoke test)")
    ap.add_argument("--out", type=Path, help="default data/imagery/sam/<scene_id>")
    args = ap.parse_args(argv)

    from backend.app.profiles import load_country

    profile = load_country(args.country)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["country"] != profile["id"]:
        raise SystemExit(f"manifest country {manifest['country']} != --country {profile['id']}")
    out_dir = args.out or (REPO_ROOT / "data" / "imagery" / "sam" / manifest["scene_id"])
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    chips = manifest["chips"][: args.limit] if args.limit else manifest["chips"]
    summary = {
        "scene_id": manifest["scene_id"], "mgrs_tile": manifest["mgrs_tile"],
        "country": manifest["country"], "demo_zone_id": manifest["demo_zone_id"],
        "prompts": args.prompts, "threshold": args.threshold,
        "min_area_px": args.min_area_px, "checkpoint_repo": CHECKPOINT_REPO,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "chips_total": len(chips), "evidence_class": "disturbed-earth patch candidates "
        "(Sentinel-2 10 m/px; NOT verified individual craters)",
    }

    def key_for(chip, prompt):
        return cache_key({"scene": manifest["scene_id"], "chip": chip["chip_id"],
                          "prompt": prompt, "threshold": args.threshold,
                          "min_area_px": args.min_area_px,
                          "checkpoint": args.checkpoint or CHECKPOINT_FILE})

    pending = [(chip, p) for chip in chips for p in args.prompts
               if not (cache_dir / f"{key_for(chip, p)}.geojson").exists()]
    summary["chips_cached"] = len(chips) * len(args.prompts) - len(pending)

    features: list[dict] = []
    if pending:
        try:
            processor, ckpt_used = load_processor(args.checkpoint, args.device, args.threshold)
        except CheckpointUnavailable as e:
            summary.update(status="failed", stage="checkpoint_load", error=str(e))
            (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(f"[sam_segment] FAILED at checkpoint load: {e}", file=sys.stderr)
            print(f"[sam_segment] failure recorded in {out_dir / 'summary.json'}")
            return 2
        summary["checkpoint_used"] = ckpt_used
        tiles_root = args.manifest.parent
        failed = []
        todo_chips = sorted({c["chip_id"] for c, _ in pending})
        by_id = {c["chip_id"]: c for c in chips}
        for chip_id in todo_chips:
            chip = by_id[chip_id]
            try:
                results = run_chip(processor, tiles_root / chip["file"],
                                   [p for c, p in pending if c["chip_id"] == chip_id],
                                   args.threshold)
            except Exception as e:  # record per-chip failure, keep going
                failed.append({"chip_id": chip_id, "error": f"{type(e).__name__}: {e}"})
                continue
            for prompt, (masks, scores) in results.items():
                feats = masks_to_features(
                    masks, scores, chip["transform"], chip["crs"],
                    {"scene_id": manifest["scene_id"], "mgrs_tile": manifest["mgrs_tile"],
                     "chip_id": chip_id, "prompt": prompt, "crs": chip["crs"]},
                    args.min_area_px)
                for f in feats:
                    f.pop("_geom", None)
                doc = {"type": "FeatureCollection", "features": feats}
                (cache_dir / f"{key_for(chip, prompt)}.geojson").write_text(
                    json.dumps(doc), encoding="utf-8")
            print(f"[sam_segment] {chip_id}: "
                  + ", ".join(f"{p}={len(v[0])}" for p, v in results.items()), flush=True)
        summary["chips_failed"] = failed

    # Merge everything in cache (fresh + resumed) and dedupe overlaps.
    from shapely.geometry import shape as shapely_shape

    merged: list[dict] = []
    for chip in chips:
        for prompt in args.prompts:
            f = cache_dir / f"{key_for(chip, prompt)}.geojson"
            if f.exists():
                for feat in json.loads(f.read_text(encoding="utf-8"))["features"]:
                    feat["_geom"] = shapely_shape(feat["geometry"])
                    merged.append(feat)
    kept = dedupe(merged)
    for f in kept:
        f.pop("_geom", None)
    doc = {"type": "FeatureCollection", "features": kept}
    (out_dir / "detections.geojson").write_text(json.dumps(doc), encoding="utf-8")
    per_prompt = {}
    for f in kept:
        st = per_prompt.setdefault(f["properties"]["prompt"], {"detections": 0, "area_m2": 0.0})
        st["detections"] += 1
        st["area_m2"] += f["properties"]["area_m2"]
    summary.update(status="ok" if not summary.get("chips_failed") else "partial",
                   detections=len(kept), per_prompt=per_prompt)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[sam_segment] {len(kept)} detections after dedupe -> {out_dir / 'detections.geojson'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
