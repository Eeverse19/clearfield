"""Unit tests for tiling/sam_segment pure helpers (no torch/rasterio/GPU)."""

import pytest
from shapely.geometry import box

from pipelines.sam_segment import cache_key, dedupe, mask_stats
from pipelines.tiling import chip_windows


def test_chip_windows_cover_with_clipped_edges():
    wins = chip_windows(100, 90, chip=32, overlap=8)  # stride 24
    assert wins[0] == (0, 0, 32, 32)
    assert max(c + w for _, c, _, w in wins) == 100
    assert max(r + h for r, _, h, _ in wins) == 90
    # every pixel row/col is covered by at least one window
    rows = set()
    for r, _, h, _ in wins:
        rows.update(range(r, r + h))
    assert rows == set(range(90))


def test_chip_windows_rejects_bad_overlap():
    with pytest.raises(ValueError):
        chip_windows(10, 10, chip=8, overlap=8)


def test_mask_stats_circle_like():
    geom = box(0, 0, 20, 20)  # 20 m square in a metre CRS
    st = mask_stats(geom)
    assert st["area_m2"] == 400.0
    assert st["equiv_diameter_m"] == pytest.approx(22.6, abs=0.1)
    assert st["circularity"] == pytest.approx(0.785, abs=0.01)  # pi/4 for a square


def _feat(x, score, prompt="disturbed earth"):
    g = box(x, 0, x + 10, 10)
    return {"type": "Feature", "geometry": None, "_geom": g,
            "properties": {"prompt": prompt, "score": score}}


def test_dedupe_keeps_higher_score_per_prompt():
    kept = dedupe([_feat(0, 0.6), _feat(1, 0.9), _feat(100, 0.7),
                   _feat(1, 0.95, prompt="bomb crater")])
    # overlapping pair collapses to the 0.9 one; far box and other prompt survive
    assert sorted(f["properties"]["score"] for f in kept) == [0.7, 0.9, 0.95]


def test_cache_key_stable_and_sensitive():
    a = cache_key({"chip": "r0_c0", "prompt": "bomb crater", "threshold": 0.5})
    b = cache_key({"prompt": "bomb crater", "chip": "r0_c0", "threshold": 0.5})
    c = cache_key({"chip": "r0_c0", "prompt": "bomb crater", "threshold": 0.4})
    assert a == b and a != c
