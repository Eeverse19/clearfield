"""Unit tests for scripts/download_worldstrat.py helpers (no network)."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "download_worldstrat",
    Path(__file__).resolve().parents[1] / "scripts" / "download_worldstrat.py",
)
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)

SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
HOLED = {"type": "MultiPolygon", "coordinates": [
    [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
     [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]],
    [[[20, 20], [30, 20], [30, 30], [20, 30], [20, 20]]],
]}


def test_point_in_geometry_basic():
    assert ws.point_in_geometry(5, 5, SQUARE)
    assert not ws.point_in_geometry(15, 5, SQUARE)


def test_point_in_geometry_hole_and_second_polygon():
    assert not ws.point_in_geometry(5, 5, HOLED)  # inside the hole
    assert ws.point_in_geometry(2, 2, HOLED)
    assert ws.point_in_geometry(25, 25, HOLED)


def test_geom_bbox():
    assert ws._geom_bbox(HOLED) == (0, 0, 30, 30)
