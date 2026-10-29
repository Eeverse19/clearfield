"""Tests for pipelines/building_exposure.py (synthetic shards, tmp DB)."""

import gzip
import json
import sqlite3
from pathlib import Path

from pipelines.building_exposure import (
    _pearson,
    building_exposure_country,
    iter_centroids,
    parse_size,
)


def test_parse_size_formats():
    assert parse_size("213B") == 213
    assert parse_size("641B") == 641
    assert parse_size("5.6MB") == 5.6e6
    assert parse_size("120.6MB") == 120.6e6
    assert parse_size("2.0KB") == 2000


def _shard(tmp_path: Path, polys: list) -> Path:
    path = tmp_path / "quadkey_test.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for coords in polys:
            feat = {"type": "Feature", "properties": {"height": -1.0},
                    "geometry": {"type": "Polygon", "coordinates": [coords]}}
            fh.write(json.dumps(feat) + "\n")
    return path


def _square(lon, lat, d=0.001):
    return [[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]


def test_iter_centroids(tmp_path):
    shard = _shard(tmp_path, [_square(100.0, 10.0), _square(101.0, 11.0)])
    pts = list(iter_centroids([shard], progress_every=0))
    assert len(pts) == 2
    assert abs(pts[0][0] - 100.0005) < 1e-6 and abs(pts[0][1] - 10.0005) < 1e-6


def test_building_exposure_writes_only_building_density(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript((Path(__file__).resolve().parents[1]
                          / "db" / "schema.local.sql").read_text(encoding="utf-8"))
    geom = {"type": "MultiPolygon",
            "coordinates": [[[[100.0, 10.0], [101.0, 10.0], [101.0, 11.0],
                              [100.0, 11.0], [100.0, 10.0]]]]}
    conn.execute("INSERT INTO zones (id, country, admin_name, geom, exposure) "
                 "VALUES ('Z1', 'laos', 'Zone1', ?, 2.5)",
                 (json.dumps(geom),))
    conn.commit()
    conn.close()
    shard = _shard(tmp_path, [_square(100.2, 10.2), _square(100.4, 10.4),
                              _square(105.0, 15.0)])  # third is outside
    summary = building_exposure_country("laos", db_path=db, shard_paths=[shard])
    conn = sqlite3.connect(db)
    density, exposure, score = conn.execute(
        "SELECT building_density, exposure, priority_score FROM zones WHERE id='Z1'"
    ).fetchone()
    conn.close()
    assert summary["assigned"] == 2 and summary["outside"] == 1
    assert density is not None and density > 0
    assert exposure == 2.5 and score is None  # other columns untouched


def test_pearson():
    assert _pearson([1, 2, 3], [2, 4, 6]) == 1.0
    assert _pearson([1, None, 3], [1, 2, None]) is None
