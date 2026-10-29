"""Regression tests for scripts/seed_db.py GeoJSON streaming."""

import importlib.util
import io
import json
import zipfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "seed_db", Path(__file__).resolve().parents[1] / "scripts" / "seed_db.py")
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


def _zip_with(text: str) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("predictions/quang_tri/crater_polygons.geojson", text)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_iter_features_skips_pretty_printed_header():
    # The real Barthelme file opens with a lone "{" line (fixed 2026-10-28:
    # it used to pass the startswith check and crash json.loads).
    feat = {"type": "Feature", "properties": {"value": 1.0},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}
    text = '{\n"type": "FeatureCollection",\n"features": [\n' \
        + json.dumps(feat) + ",\n" + json.dumps(feat) + "\n]\n}\n"
    counters = {"features": 0, "unparsed": 0}
    got = list(seed.iter_features(
        _zip_with(text), "predictions/quang_tri/crater_polygons.geojson", counters))
    assert len(got) == 2 and counters == {"features": 2, "unparsed": 0}


def test_zone_hits_finds_containing_zone():
    # Regression (2026-10-28): predicate="covers" returned no hits for
    # every crater centroid, so the seed reconciled with 0 craters.
    from shapely import STRtree
    from shapely.geometry import Point, box

    zones = [box(100, 10, 102, 12), box(102, 10, 104, 12)]
    tree = STRtree(zones)
    assert seed.zone_hits(tree, Point(101, 11)) == [0]
    assert seed.zone_hits(tree, Point(103, 11)) == [1]
    assert seed.zone_hits(tree, Point(99, 11)) == []


def test_iter_features_counts_unparsable_lines():
    text = '{ "type": "Feature", "properties": {}, "geometry": null},\n{not json}\n'
    counters = {"features": 0, "unparsed": 0}
    got = list(seed.iter_features(
        _zip_with(text), "predictions/quang_tri/crater_polygons.geojson", counters))
    assert len(got) == 1 and counters["unparsed"] == 1
