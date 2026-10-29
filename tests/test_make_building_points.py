"""Writer <-> reader round-trip for building centroid points.

scripts/make_building_points.py writes data/buildings/{Location}/
centroids.f32 (float32-le lon,lat pairs); backend get_buildings reads
exactly that file. This writes a synthetic shard through the real
writer and reads it back through the real endpoint handler, so a
format/order drift on either side fails here. No network: the shard
download is stubbed to a local synthetic shard.
"""

import array
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "make_building_points",
    Path(__file__).resolve().parents[1] / "scripts" / "make_building_points.py",
)
mbp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mbp)

from backend.app.main import get_buildings  # noqa: E402


def _shard(tmp_path: Path) -> Path:
    path = tmp_path / "quadkey_test.csv.gz"
    squares = [(100.0, 10.0), (101.0, 11.0), (105.0, 20.0)]
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for lon, lat in squares:
            d = 0.001
            coords = [[lon, lat], [lon + d, lat], [lon + d, lat + d],
                      [lon, lat + d], [lon, lat]]
            feat = {"type": "Feature", "properties": {"height": -1.0},
                    "geometry": {"type": "Polygon", "coordinates": [coords]}}
            fh.write(json.dumps(feat) + "\n")
    return path


def test_writer_output_is_readable_by_buildings_endpoint(tmp_path, monkeypatch):
    buildings_dir = tmp_path / "buildings"
    shard = _shard(tmp_path)
    monkeypatch.setattr(mbp, "BUILDINGS_DIR", buildings_dir)
    monkeypatch.setattr(mbp, "download_shards", lambda country: [shard])

    assert mbp.main(["--country", "laos"]) == 0

    manifest = json.loads(
        (buildings_dir / "Laos" / "points_manifest.json").read_text(encoding="utf-8"))
    assert manifest["points"] == 3

    resp = get_buildings("laos", buildings_dir=buildings_dir)
    assert resp.headers["x-building-total"] == "3"
    pts = array.array("f")
    pts.frombytes(resp.body)
    pairs = [(pts[i], pts[i + 1]) for i in range(0, len(pts), 2)]
    # (lon, lat) order: float32 precision, far tighter than a swap.
    assert pairs[0] == pytest.approx((100.0005, 10.0005), abs=1e-3)
    assert pairs[1] == pytest.approx((101.0005, 11.0005), abs=1e-3)

    # bbox filtering in the reader agrees with writer coordinates.
    resp = get_buildings("laos", bbox="99,9,102,12", buildings_dir=buildings_dir)
    assert resp.headers["x-building-count"] == "2"
