"""Unit tests for scripts/kh9_match.py pure helpers (no frames, no DB).

kh9_match emits coordinates for ~541k craters, so these pin the
catastrophic-if-wrong pieces: GeoJSON centroid axis order, the
EPSG:4326 -> EPSG:32648 (UTM 48N) transform at known points, and the
coarse valid-pixel mask indexing. rasterio is not required: the module
imports it optionally and make_transformer uses pyproj in .venv.
"""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "kh9_match",
    Path(__file__).resolve().parents[1] / "scripts" / "kh9_match.py",
)
km = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(km)


def test_parse_centroid_is_lon_lat_not_swapped():
    # GeoJSON Point order is [lon, lat]; a swap would move every crater.
    assert km.parse_centroid(
        '{"type": "Point", "coordinates": [106.5, 16.8]}') == (106.5, 16.8)
    assert km.parse_centroid(
        '{"type": "Point", "coordinates": [100.25, 5.5]}') == (100.25, 5.5)


@pytest.mark.parametrize("text", [
    None,
    "",
    "not json",
    '{"type": "Point"}',
    '{"coordinates": [106.5]}',
    '{"coordinates": ["east", "north"]}',
])
def test_parse_centroid_unusable_returns_none(text):
    assert km.parse_centroid(text) is None


def test_transform_central_meridian_definition():
    batch, _desc = km.make_transformer()
    assert batch is not None
    # UTM definition: the zone 48N central meridian (105E) at the equator
    # is exactly (500000, 0). Any lon/lat swap breaks this outright.
    xs, ys = batch([105.0], [0.0])
    assert xs[0] == pytest.approx(500_000.0, abs=1e-3)
    assert ys[0] == pytest.approx(0.0, abs=1e-3)
    # Due north along the central meridian: easting stays 500000.
    xs, ys = batch([105.0], [10.0])
    assert xs[0] == pytest.approx(500_000.0, abs=1e-3)
    assert ys[0] == pytest.approx(1_105_412.49, rel=1e-6)


def test_transform_known_point_and_zone_edges():
    batch, _desc = km.make_transformer()
    # Quang Tri area: easting well east of the central meridian,
    # northing just under 1.86M. A swap would put this off-globe.
    xs, ys = batch([107.0], [16.8])
    assert xs[0] == pytest.approx(713_147.28, rel=1e-6)
    assert ys[0] == pytest.approx(1_858_505.80, rel=1e-6)
    # Zone edges at the equator are symmetric about 500000.
    west, _ = batch([102.0], [0.0])
    east, _ = batch([108.0], [0.0])
    assert west[0] == pytest.approx(166_021.44, rel=1e-6)
    assert east[0] == pytest.approx(833_978.56, rel=1e-6)
    assert west[0] + east[0] == pytest.approx(1_000_000.0, abs=1e-3)


def test_transform_batch_preserves_order():
    batch, _desc = km.make_transformer()
    xs, ys = batch([105.0, 107.0], [0.0, 16.8])
    assert len(xs) == len(ys) == 2
    assert xs[0] < xs[1] and ys[0] < ys[1]


def _frame(valid_mask):
    return km.Frame(
        area="test", filename="frame-8mpp.tif", path=Path("frame-8mpp.tif"),
        crs="EPSG:32648", bounds=(0.0, 0.0, 0.0, 0.0),
        transform=None, inv_transform=None, width=0, height=0,
        valid_mask=valid_mask,
    )


def test_pixel_valid_mask_cells_are_row_then_col():
    np = pytest.importorskip("numpy")
    # Asymmetric 2 rows x 3 cols mask (MASK_SCALE=16 px per cell):
    # only cell (row 0, col 1) and (row 1, col 2) are valid.
    mask = np.array([[False, True, False],
                     [False, False, True]])
    frame = _frame(mask)
    assert frame.pixel_valid(col=20, row=5)      # cell (0, 1)
    assert not frame.pixel_valid(col=5, row=20)  # cell (1, 0): swapped would pass
    assert frame.pixel_valid(col=47, row=31)     # cell (1, 2)
    assert not frame.pixel_valid(col=31, row=47)  # row cell 2: out of mask


def test_pixel_valid_boundaries_and_no_mask():
    np = pytest.importorskip("numpy")
    frame = _frame(np.array([[True]]))
    assert frame.pixel_valid(col=0, row=0)
    assert frame.pixel_valid(col=15.9, row=15.9)
    assert not frame.pixel_valid(col=16, row=0)
    assert not frame.pixel_valid(col=0, row=16)
    assert not frame.pixel_valid(col=-1, row=0)
    assert not frame.pixel_valid(col=0, row=-1)
    # No mask loaded -> every in-frame pixel counts as valid.
    assert _frame(None).pixel_valid(col=9999, row=9999)
