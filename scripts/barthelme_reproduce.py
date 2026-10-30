"""Reproduce Barthelme U-Net crater scores on their own test tiles.

Usage (.venv-unet, see below):
  .venv-unet\\Scripts\\python.exe scripts/barthelme_reproduce.py [--area quang_tri]

What this does:
1. Extracts per-area data.h5 from data/barthelme/data.zip (once) to
   data/barthelme/unpacked/.
2. Converts each models.zip final_model.pth (a whole pickled smp Unet,
   MD5-pinned in docs/data-manifest.md) into a plain state_dict at
   data/barthelme/models_extracted/{area}_state_dict.pth — the one
   trusted weights_only=False load; everything after uses
   weights_only=True.
3. Runs inference on the H5 test split exactly per the authors'
   recipe (config.yaml/notebook 5): per-tile min-max scaling to [0,1],
   argmax over 7 classes, class 6 (boundary) -> 0, remove objects and
   holes < 25 px, instances = connected components of class>0, each
   instance's class = majority pixel class.
4. Scores instances against the H5 labels (instances derived the same
   way from the one-hot ground truth): greedy IoU>=0.5 matching,
   combined-crater precision/recall/F1 (per-object), plus pixel F1.
   Published targets (tables.zip / paper): Quang Tri per-object F1
   0.64 (P 0.68 / R 0.60), pixel F1 0.65; tri-border 0.44 / 0.41.
   Near-but-not-bit-identical is expected (torch 2.10 vs their 2.0.1).

Outputs: data/barthelme/reproduction/{area}_report.json + console.
This validates the detector before it is trusted on new KH-9 areas;
it produces no zone data and writes nothing to the DB.

Env (separate from .venv-sam on purpose — smp 0.3.3 pins old timm):
  py -3.12 -m venv .venv-unet
  .venv-unet\\Scripts\\python.exe -m pip install torch==2.10.0 torchvision --index-url https://download.pytorch.org/whl/cu128
  .venv-unet\\Scripts\\python.exe -m pip install segmentation-models-pytorch==0.3.3 h5py scikit-image numpy pillow
"""

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BARTHELME = REPO_ROOT / "data" / "barthelme"
AREAS = ("quang_tri", "tri_border_area")
TARGETS = {  # tables.zip / Barthelme et al. 2024, per-object IoU>=0.5 + pixel
    "quang_tri": {"object_f1": 0.64, "object_p": 0.68, "object_r": 0.60, "pixel_f1": 0.65},
    "tri_border_area": {"object_f1": 0.44, "object_p": 0.58, "object_r": 0.35, "pixel_f1": 0.41},
}
MIN_AREA = 25  # authors' minimum crater size in px (25 m2 at 1 m/px)


def extract_h5(area: str) -> Path:
    dest = BARTHELME / "unpacked" / area / "data.h5"
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    member = f"data/2_training_data/{area}/data.h5"
    print(f"extracting {member} -> {dest}")
    with zipfile.ZipFile(BARTHELME / "data.zip") as zf:
        with zf.open(member) as src, dest.open("wb") as out:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                out.write(chunk)
    return dest


def extract_state_dict(area: str) -> Path:
    """One trusted full-pickle load -> safe state_dict (see docstring)."""
    import torch

    dest = BARTHELME / "models_extracted" / f"{area}_state_dict.pth"
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BARTHELME / "models.zip") as zf:
        raw = zf.read(f"models/{area}/final_model.pth")
    model = torch.load(io.BytesIO(raw), weights_only=False, map_location="cpu")
    torch.save(model.state_dict(), dest)
    print(f"{area}: state_dict extracted ({len(model.state_dict())} keys) -> {dest}")
    return dest


def build_model(state_dict_path: Path, device: str):
    import segmentation_models_pytorch as smp
    import torch

    model = smp.Unet(encoder_name="resnet50", encoder_weights=None,
                     in_channels=1, classes=7, activation=None)
    state = torch.load(state_dict_path, weights_only=True, map_location="cpu")
    model.load_state_dict(state)
    return model.to(device).eval()


def postprocess(pred_classes):
    """Authors' recipe: 6->0, drop <25px objects/holes, majority class."""
    import numpy as np
    from skimage import measure, morphology

    arr = pred_classes.copy()
    arr[arr == 6] = 0
    binary = arr > 0
    binary = morphology.remove_small_holes(binary, area_threshold=MIN_AREA)
    binary = morphology.remove_small_objects(binary, min_size=MIN_AREA)
    instances = measure.label(binary, connectivity=1)
    classes = np.zeros(instances.max() + 1, dtype=np.uint8)
    for i in range(1, instances.max() + 1):
        vals, counts = np.unique(arr[instances == i][arr[instances == i] > 0],
                                 return_counts=True)
        if len(vals):
            classes[i] = vals[counts.argmax()]
    return instances, classes


def instances_from_label(label_classes):
    """Ground-truth instances: same component rule, boundary excluded."""
    import numpy as np
    from skimage import measure

    binary = (label_classes > 0) & (label_classes < 6)
    instances = measure.label(binary, connectivity=1)
    classes = np.zeros(instances.max() + 1, dtype=np.uint8)
    for i in range(1, instances.max() + 1):
        vals, counts = np.unique(label_classes[instances == i], return_counts=True)
        classes[i] = vals[counts.argmax()]
    return instances, classes


def match_score(pred_inst, pred_cls, true_inst, true_cls):
    """Greedy IoU>=0.5 instance matching -> combined P/R/F1 counts."""
    import numpy as np

    n_pred = int(pred_inst.max())
    n_true = int(true_inst.max())
    matched_true = set()
    tp = 0
    for p in range(1, n_pred + 1):
        pmask = pred_inst == p
        overlap_ids, counts = np.unique(true_inst[pmask], return_counts=True)
        best, best_iou = None, 0.0
        for tid, inter in zip(overlap_ids.tolist(), counts.tolist()):
            if tid == 0 or tid in matched_true:
                continue
            union = pmask.sum() + (true_inst == tid).sum() - inter
            iou = inter / union if union else 0.0
            if iou > best_iou:
                best, best_iou = tid, iou
        if best is not None and best_iou >= 0.5:
            tp += 1
            matched_true.add(best)
    return tp, n_pred, n_true


def run_area(area: str, device: str, batch: int = 32) -> dict:
    import h5py
    import numpy as np
    import torch

    h5_path = extract_h5(area)
    model = build_model(extract_state_dict(area), device)
    tp = n_pred_total = n_true_total = 0
    inter_px = pred_px = true_px = 0
    with h5py.File(h5_path, "r") as h5:
        x_test, y_test = h5["x_test"], h5["y_test"]
        print(f"{area}: test tiles {x_test.shape}")
        for start in range(0, x_test.shape[0], batch):
            xb = np.asarray(x_test[start:start + batch], dtype=np.float32)
            yb = np.asarray(y_test[start:start + batch])
            # Authors' scaling: per-tile min-max to [0,1].
            mins = xb.min(axis=(1, 2, 3), keepdims=True)
            maxs = xb.max(axis=(1, 2, 3), keepdims=True)
            xb = (xb - mins) / np.maximum(maxs - mins, 1e-9)
            with torch.no_grad():
                logits = model(torch.from_numpy(xb).permute(0, 3, 1, 2).to(device))
            pred = logits.argmax(dim=1).cpu().numpy().astype(np.uint8)
            labels = yb.argmax(axis=-1).astype(np.uint8)
            for i in range(pred.shape[0]):
                p_inst, _ = postprocess(pred[i])
                t_inst, _ = instances_from_label(labels[i])
                a, b, c = match_score(p_inst, None, t_inst, None)
                tp += a; n_pred_total += b; n_true_total += c
                pb, tb = p_inst > 0, t_inst > 0
                inter_px += int((pb & tb).sum()); pred_px += int(pb.sum()); true_px += int(tb.sum())
            print(f"  {min(start + batch, x_test.shape[0])}/{x_test.shape[0]} tiles", flush=True)
    p = tp / n_pred_total if n_pred_total else 0.0
    r = tp / n_true_total if n_true_total else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    pp = inter_px / pred_px if pred_px else 0.0
    rr = inter_px / true_px if true_px else 0.0
    report = {
        "area": area,
        "instances_pred": n_pred_total, "instances_true": n_true_total, "tp": tp,
        "object_precision": round(p, 4), "object_recall": round(r, 4),
        "object_f1": round(f1, 4),
        "pixel_precision": round(pp, 4), "pixel_recall": round(rr, 4),
        "pixel_f1": round(2 * pp * rr / (pp + rr), 4) if (pp + rr) else 0.0,
        "published_target": TARGETS[area],
        "note": "Greedy IoU>=0.5 combined-crater matching (this script); "
                "authors' evaluation.py may differ in detail.",
    }
    out_dir = BARTHELME / "reproduction"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{area}_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--area", choices=AREAS, default=None, help="default: both")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args(argv)
    for area in ([args.area] if args.area else list(AREAS)):
        run_area(area, args.device, args.batch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
