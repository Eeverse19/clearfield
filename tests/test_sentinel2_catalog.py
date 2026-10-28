"""Unit tests for scripts/sentinel2_catalog.py (no network)."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "sentinel2_catalog",
    Path(__file__).resolve().parents[1] / "scripts" / "sentinel2_catalog.py",
)
cat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cat)


def test_months_crosses_year_boundary():
    got = list(cat.months((2024, 11), (2025, 2)))
    assert [ym for ym, _, _ in got] == [(2024, 11), (2024, 12), (2025, 1), (2025, 2)]
    assert got[0][1:] == ("2024-11-01T00:00:00Z", "2024-12-01T00:00:00Z")
    assert got[-1][2] == "2025-03-01T00:00:00Z"


def test_parse_month():
    assert cat.parse_month("2015-06") == (2015, 6)


def _task(ym):
    return {"country": "laos", "collection": "sentinel-2-l2a", "ym": ym,
            "t0": "", "t1": "", "geometry": {}, "parts": None}


def test_run_tasks_isolates_and_retries_failures():
    attempts = {}

    def fake_fetch(task):
        key = cat.slice_key(task)
        attempts[key] = attempts.get(key, 0) + 1
        if task["ym"] == (2024, 2) and attempts[key] == 1:
            raise RuntimeError("HTTP 502")  # succeeds on the page-size-100 retry
        if task["ym"] == (2024, 3):
            raise RuntimeError("HTTP 502")  # never succeeds
        assert task.get("page_limit", 250) in (100, 250)
        return key, 10, False

    total, failed = cat.run_tasks([_task((2024, 1)), _task((2024, 2)), _task((2024, 3))],
                                  workers=2, fetch=fake_fetch)
    assert total == 20
    assert [cat.slice_key(t) for t in failed] == ["laos_sentinel-2-l2a_2024-03"]


def test_feature_row_extracts_rgb_nir_only():
    feature = {
        "id": "S2A_47PPR_20240131_0_L2A",
        "bbox": [100.0, 14.0, 101.0, 15.0],
        "geometry": {"type": "Polygon", "coordinates": []},
        "properties": {
            "datetime": "2024-01-31T03:54:21.227000Z",
            "grid:code": "MGRS-47PPR",
            "platform": "sentinel-2a",
            "eo:cloud_cover": 18.5,
        },
        "assets": {
            "blue": {"href": "https://x/B02.tif"},
            "green": {"href": "https://x/B03.tif"},
            "red": {"href": "https://x/B04.tif"},
            "nir": {"href": "https://x/B08.tif"},
            "swir16": {"href": "https://x/B11.tif"},
        },
        "links": [{"rel": "self", "href": "https://stac/items/1"}],
    }
    row = dict(zip(cat.CSV_FIELDS, cat.feature_row("laos", "sentinel-2-l2a", feature)))
    assert row["mgrs_tile"] == "47PPR"
    assert row["cloud_cover"] == 18.5
    assert row["b02_href"] == "https://x/B02.tif"
    assert row["b08_href"] == "https://x/B08.tif"
    assert all("B11" not in str(v) for v in row.values())
    assert row["item_href"] == "https://stac/items/1"
