"""Endpoint handler tests.

Handlers are called directly instead of through FastAPI TestClient: the
sandboxed shell forbids socket listen (WinError 10013), which the asyncio
event loop behind TestClient needs for its self-pipe. Direct calls cover the
handlers; ASGI routing tests can switch to TestClient in CI.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app import config
from backend.app.main import (countries, country, create_find, explain,
                              get_buildings, health, index, list_zones)

SCHEMA = Path(__file__).resolve().parents[1] / "db" / "schema.local.sql"
GEOM = '{"type": "MultiPolygon", "coordinates": []}'


def make_db(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO zones (id, country, admin_name, geom, crater_evidence,"
        " surveyed_status, priority_score, priority_rank) VALUES (?,?,?,?,?,?,?,?)",
        [("LAO.2_1", "laos", "B", GEOM, None, "unsurveyed", 0.5, 2),
         ("LAO.1_1", "laos", "A", GEOM, 2.14, "unsurveyed", 0.9, 1),
         ("LAO.3_1", "laos", "C", GEOM, None, "surveyed", None, None),
         ("KHM.1_1", "cambodia", "K", GEOM, None, "unsurveyed", None, None)])
    conn.commit()
    conn.close()
    return path


def status_of(fn):
    with pytest.raises(HTTPException) as exc:
        fn()
    return exc.value.status_code


def test_health():
    body = health()
    assert body["status"] == "ok" and body["scaffold"] is True


def test_countries():
    assert country("laos")["languages"] == ["en", "lo"]
    assert {"laos", "cambodia", "vietnam"} <= {p["id"] for p in countries()}
    assert status_of(lambda: country("narnia")) == 404


def test_zones_order_envelope_and_null_fidelity(tmp_path):
    db = make_db(tmp_path)
    out = list_zones("laos", db_path=db)
    assert (out["country"], out["count"], out["total"]) == ("laos", 3, 3)
    ids = [z["id"] for z in out["zones"]]
    assert ids == ["LAO.1_1", "LAO.2_1", "LAO.3_1"]  # ranked first, unscored last
    first = out["zones"][0]
    assert first["geom"] == {"type": "MultiPolygon", "coordinates": []}
    assert first["strike_density"] is None and first["exposure"] is None  # never 0
    assert out["zones"][2]["priority_rank"] is None
    page = list_zones("laos", limit=2, offset=2, db_path=db)
    assert page["total"] == 3 and [z["id"] for z in page["zones"]] == ["LAO.3_1"]
    assert [z["id"] for z in list_zones("laos", include_unscored=False, db_path=db)["zones"]] \
        == ["LAO.1_1", "LAO.2_1"]
    assert [z["id"] for z in list_zones("laos", surveyed_status="surveyed", db_path=db)["zones"]] \
        == ["LAO.3_1"]


def test_zones_errors(tmp_path):
    db = make_db(tmp_path)
    assert status_of(lambda: list_zones("narnia", db_path=db)) == 404
    assert status_of(lambda: list_zones("laos", surveyed_status="bogus", db_path=db)) == 422
    assert status_of(lambda: list_zones("laos", limit=0, db_path=db)) == 422
    assert status_of(lambda: list_zones("laos", offset=-1, db_path=db)) == 422
    assert status_of(lambda: list_zones("laos", db_path=tmp_path / "missing.db")) == 503


FIND = {"id": "f1", "country": "laos", "zone_id": "LAO.1_1", "object_type": "bomblet",
        "location": {"type": "Point", "coordinates": [105.0, 15.0]}}


def test_find_roundtrip_and_replay(tmp_path):
    db = make_db(tmp_path)
    record, status = create_find(dict(FIND), db_path=db)
    assert status == 201 and record["risk_flag"] == "unknown" and record["synced_at"]
    again, status = create_find(dict(FIND), db_path=db)
    assert status == 200 and again["id"] == "f1"
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM finds").fetchone()[0] == 1
    # A find never changes scores; re-scoring is pipelines/scoring.py only.
    assert conn.execute("SELECT priority_rank FROM zones WHERE id='LAO.1_1'").fetchone()[0] == 1
    conn.close()
    assert status_of(lambda: create_find({**FIND, "notes": "different"}, db_path=db)) == 409


def test_find_validation(tmp_path):
    db = make_db(tmp_path)
    cases = [
        ({**FIND, "id": "x1", "risk_flag": "safe"}, 422),
        ({**FIND, "id": "x2", "location": {"type": "Point", "coordinates": [999, 0]}}, 422),
        ({**FIND, "id": "x3", "location": {"type": "Polygon", "coordinates": []}}, 422),
        ({**FIND, "id": "x4", "zone_id": "LAO.99_1"}, 422),
        ({**FIND, "id": "x5", "zone_id": "KHM.1_1"}, 422),  # zone of another country
        ({**FIND, "id": "x6", "country": "narnia"}, 404),
        ({**FIND, "id": "x7", "synced_at": "2026-01-01"}, 422),
        ({**FIND, "id": "x8", "surprise": 1}, 422),
        ({"country": "laos"}, 422),
    ]
    for payload, want in cases:
        assert status_of(lambda p=payload: create_find(p, db_path=db)) == want, payload
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM finds").fetchone()[0] == 0  # no partial writes
    conn.close()
    assert status_of(lambda: create_find(dict(FIND), db_path=tmp_path / "missing.db")) == 503


def test_buildings_points_bbox_and_missing(tmp_path):
    import array as _array

    d = tmp_path / "Laos"
    d.mkdir(parents=True)
    pts = _array.array("f", [100.0, 10.0, 101.0, 11.0, 105.0, 20.0])
    (d / "centroids.f32").write_bytes(pts.tobytes())
    resp = get_buildings("laos", bbox="99,9,102,12", buildings_dir=tmp_path)
    assert resp.headers["x-building-count"] == "2"
    assert resp.headers["x-building-total"] == "3"
    assert len(resp.body) == 2 * 2 * 4
    resp = get_buildings("laos", limit=1, buildings_dir=tmp_path)
    assert resp.headers["x-building-truncated"] == "true"
    assert status_of(lambda: get_buildings("cambodia", buildings_dir=tmp_path)) == 404
    assert status_of(lambda: get_buildings("atlantis", buildings_dir=tmp_path)) == 404
    assert status_of(lambda: get_buildings("laos", bbox="bad", buildings_dir=tmp_path)) == 422


def test_explain_still_honest_501():
    assert status_of(explain) == 501


def test_index_serves_frontend_gui():
    resp = index()
    assert resp.status_code == 200
    assert resp.media_type == "text/html"
    body = Path(resp.path).read_text(encoding="utf-8")
    assert "ClearField" in body and 'id="map"' in body and "/zones?country=" in body
    # UX-skill pass guards: live region, keyboard-reachable map, demo zone join key.
    assert 'aria-live="polite"' in body and 'tabindex="0"' in body and "demo_zone_id" in body
    # Visualization-spec guards: honest layers, missing-data treatment, attribution.
    for needle in ("Official priority", "Strike records (THOR)", "Data coverage",
                   "not verified impacts", "OpenStreetMap contributors",
                   "not zero, not low, not safe", "Unscorable", "◆ DEMO",
                   "country max", "Math.log1p",
                    'id="btn-basemap"', "World_Imagery/MapServer/export", "s2cloudless-2024"):
        assert needle in body, needle
    for stale in ("THOR pending", "A real zero gets the lightest", "needs the THOR ingest"):
        assert stale not in body, stale


@pytest.mark.skipif(not config.LOCAL_DB_PATH.exists(), reason="real seeded DB not present")
def test_real_db_zones_smoke():
    out = list_zones("laos", limit=500)
    assert out["total"] == 18
    # 4 after the 2026-10-26 false-zero correction (LAO.11_1 -> NULL).
    assert sum(1 for z in out["zones"] if z["crater_evidence"] is not None) == 4
    # THOR seeded + scoring run 2026-10-28: strike on all 18; only the
    # 4 zones with crater_evidence are ranked (observed ranks 1-4).
    assert all(z["strike_density"] is not None for z in out["zones"])
    ranked = {z["id"] for z in out["zones"] if z["priority_rank"] is not None}
    assert ranked == {"LAO.1_1", "LAO.4_1", "LAO.17_1", "LAO.12_1"}
