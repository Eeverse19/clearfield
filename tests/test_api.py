"""Endpoint handler tests.

Handlers are called directly instead of through FastAPI TestClient: the
sandboxed shell forbids socket listen (WinError 10013), which the asyncio
event loop behind TestClient needs for its self-pipe. Direct calls cover the
handlers; ASGI routing tests can switch to TestClient in CI.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app import config
from backend.app.main import (build_cached_explanation, countries, country,
                              create_find, explain, explain_request,
                              get_buildings, get_craters, get_kh9_frames,
                              get_worldstrat_chips, health, index, list_zones)

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


def test_craters_points_bbox_and_missing(tmp_path):
    import array as _array

    pts = _array.array("f", [106.8, 17.0, 100.0, 10.0, 107.5, 16.5])
    (tmp_path / "crater_points_vietnam.f32").write_bytes(pts.tobytes())
    resp = get_craters("vietnam", bbox="106,16,108,18", kh9_dir=tmp_path)
    assert resp.headers["x-crater-count"] == "2"
    assert resp.headers["x-crater-total"] == "3"
    assert status_of(lambda: get_craters("laos", kh9_dir=tmp_path)) == 404
    assert status_of(lambda: get_craters("ukraine", kh9_dir=tmp_path)) == 404


def test_kh9_frames_geojson(tmp_path):
    import json as _json

    doc = {"frames": [{"frame": "F1-8mpp.tif", "area": "quang_tri", "count": 7,
                       "bounds_epsg32648": {"left": 500000, "bottom": 1800000,
                                            "right": 600000, "top": 1900000}}]}
    (tmp_path / "kh9_match_summary.json").write_text(_json.dumps(doc), encoding="utf-8")
    out = get_kh9_frames(kh9_dir=tmp_path)
    f = out["features"][0]
    assert f["properties"]["frame"] == "F1-8mpp.tif"
    assert f["properties"]["date"] == "1973-03-20"
    ring = f["geometry"]["coordinates"][0]
    assert len(ring) == 5 and ring[0] == ring[-1]
    assert 100 < ring[0][0] < 110 and 15 < ring[0][1] < 18  # lon/lat, not UTM
    assert status_of(lambda: get_kh9_frames(kh9_dir=tmp_path / "nope")) == 404


def test_worldstrat_chips_geojson(tmp_path):
    (tmp_path / "index.csv").write_text(
        "chip_id,country,dir,lon,lat,bounds,highres_date,area_km2,lccs_class,"
        "smod_class,lowres_dates,files_extracted\n"
        "Landcover-1,laos,Landcover-1,103.2,20.2,"
        "\"[103.1, 20.1, 103.3, 20.3]\",2021-04-16,2.5,,,,\n", encoding="utf-8")
    out = get_worldstrat_chips(worldstrat_dir=tmp_path)
    f = out["features"][0]
    assert f["properties"]["chip_id"] == "Landcover-1"
    assert f["geometry"]["coordinates"][0][2] == [103.3, 20.3]
    assert status_of(lambda: get_worldstrat_chips(worldstrat_dir=tmp_path / "x")) == 404


def test_explain_live_spark_on_cache_miss(tmp_path, monkeypatch):
    from backend.app import main as backend_main

    db = make_db(tmp_path)
    monkeypatch.setattr(backend_main.spark_agent, "_api_key", lambda: "k")
    monkeypatch.setattr(backend_main.spark_agent, "explain_zone",
                        lambda row, lang="en": f"live:{row['id']}:{lang}")
    out = backend_main.explain_request(
        {"zone_id": "LAO.1_1", "lang": "en"}, db_path=db, cached_dir=tmp_path)
    assert out["source"] == "live" and out["origin"] == "muse_spark_live"
    assert out["explanation"] == "live:LAO.1_1:en"
    assert out["score_components"]["crater_evidence"] == 2.14


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


# --- /explain (cache-first) -------------------------------------------------
# Fixture row for LAO.1_1 as make_db stores it (nulls are legal in the
# cache format; only the generator refuses to seed unranked/unscorable rows).
EXPLAIN_ROW = {"id": "LAO.1_1", "country": "laos", "admin_name": "A",
               "strike_density": None, "crater_evidence": 2.14,
               "exposure": None, "surveyed_status": "unsurveyed",
               "priority_score": 0.9, "priority_rank": 1, "scored_at": None}


def make_cache(tmp_path, payload=None):
    path = tmp_path / "explain-LAO.1_1-en.json"
    data = build_cached_explanation(dict(EXPLAIN_ROW)) if payload is None else payload
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return tmp_path


def explain_exc(payload, **kwargs):
    with pytest.raises(HTTPException) as exc:
        explain_request(payload, **kwargs)
    return exc.value


def test_explain_cache_hit_no_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "META_API_KEY", "")  # hit must need no key
    db = make_db(tmp_path)
    cached_dir = tmp_path / "cache"
    cached_dir.mkdir()
    make_cache(cached_dir)
    out = explain_request({"zone_id": "LAO.1_1"}, db_path=db,
                          cached_dir=cached_dir)
    assert set(out) == {"zone_id", "country", "admin_name", "lang",
                        "requested_lang", "source", "origin", "explanation",
                        "score_components"}
    assert (out["zone_id"], out["country"], out["admin_name"]) == \
        ("LAO.1_1", "laos", "A")
    assert out["source"] == "cache"
    assert out["origin"] == "template_from_stored_components"
    assert out["lang"] == out["requested_lang"] == "en"
    assert out["score_components"] == {
        "strike_density": None, "crater_evidence": 2.14, "exposure": None,
        "surveyed_status": "unsurveyed", "priority_score": 0.9,
        "priority_rank": 1, "scored_at": None}
    # utf-8 read on Windows: the template's km² must not arrive as mojibake.
    assert "km²" in out["explanation"] and "Â" not in out["explanation"]
    # Explicit matching country is accepted too.
    out2 = explain_request({"zone_id": "LAO.1_1", "country": "laos"},
                           db_path=db, cached_dir=cached_dir)
    assert out2["zone_id"] == "LAO.1_1"


def test_explain_en_fallback_is_labeled(tmp_path):
    db = make_db(tmp_path)
    cached_dir = tmp_path / "cache"
    cached_dir.mkdir()
    make_cache(cached_dir)
    out = explain_request({"zone_id": "LAO.1_1", "lang": "lo"},
                          db_path=db, cached_dir=cached_dir)
    assert out["lang"] == "en" and out["requested_lang"] == "lo"
    out = explain_request({"zone_id": "LAO.1_1", "lang": " KM "},
                          db_path=db, cached_dir=cached_dir)
    assert out["lang"] == "en" and out["requested_lang"] == "km"


def test_explain_miss_still_501(tmp_path, monkeypatch):
    from backend.app import main as backend_main

    db = make_db(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    # Pin "no key anywhere": config and the .env fallback both empty.
    monkeypatch.setattr(config, "META_API_KEY", "")
    monkeypatch.setattr(backend_main.spark_agent, "_api_key", lambda: "")
    exc = explain_exc({"zone_id": "LAO.1_1"}, db_path=db, cached_dir=empty)
    assert exc.status_code == 501
    assert exc.detail == ("explain not implemented: META_API_KEY not set "
                          "(Spark runs on stored score components only)")
    # With a key, a miss goes live; an upstream failure is a 502, not 501.
    monkeypatch.setattr(backend_main.spark_agent, "_api_key", lambda: "k")

    def _boom(row, lang="en"):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(backend_main.spark_agent, "explain_zone", _boom)
    exc = explain_exc({"zone_id": "LAO.1_1"}, db_path=db, cached_dir=empty)
    assert exc.status_code == 502
    # An unseeded (unranked) zone is a miss, not a special case.
    monkeypatch.setattr(backend_main.spark_agent, "_api_key", lambda: "")
    exc = explain_exc({"zone_id": "LAO.3_1"}, db_path=db, cached_dir=empty)
    assert exc.status_code == 501


def test_explain_stale_cache_is_miss(tmp_path, monkeypatch):
    from backend.app import main as backend_main

    monkeypatch.setattr(config, "META_API_KEY", "")
    monkeypatch.setattr(backend_main.spark_agent, "_api_key", lambda: "")
    db = make_db(tmp_path)
    cached_dir = tmp_path / "cache"
    cached_dir.mkdir()
    payload = build_cached_explanation(dict(EXPLAIN_ROW))
    payload["score_components"] = {**payload["score_components"],
                                    "priority_score": 0.123}
    make_cache(cached_dir, payload)
    exc = explain_exc({"zone_id": "LAO.1_1"}, db_path=db, cached_dir=cached_dir)
    assert exc.status_code == 501  # re-scored zone never serves old numbers


def test_explain_malformed_cache_503(tmp_path):
    db = make_db(tmp_path)
    cached_dir = tmp_path / "cache"
    cached_dir.mkdir()
    path = cached_dir / "explain-LAO.1_1-en.json"
    good = build_cached_explanation(dict(EXPLAIN_ROW))
    variants = [
        "{not json",
        json.dumps(["not", "an", "object"]),
        json.dumps({**good, "zone_id": "LAO.2_1"}),
        json.dumps({**good, "admin_name": "Renamed"}),
        json.dumps({**good, "explanation": "hand-written text"}),
        json.dumps({**good, "score_components": {
            **good["score_components"], "strike_density": True}}),
        json.dumps({**good, "score_components": {
            **good["score_components"], "priority_rank": True}}),
        json.dumps({k: v for k, v in good.items() if k != "origin"}),
    ]
    for text in variants:
        path.write_text(text, encoding="utf-8")
        exc = explain_exc({"zone_id": "LAO.1_1"}, db_path=db,
                          cached_dir=cached_dir)
        assert exc.status_code == 503, text


def test_explain_validation(tmp_path):
    db = make_db(tmp_path)
    cases = [
        ("nope", 422), ([], 422), (None, 422),
        ({}, 422),
        ({"zone_id": "LAO.1_1", "surprise": 1}, 422),
        ({"zone_id": ""}, 422), ({"zone_id": "   "}, 422),
        ({"zone_id": 123}, 422), ({"zone_id": None}, 422),
        ({"zone_id": "lao.1_1"}, 422),
        ({"zone_id": "LAO.1_1", "lang": "fr"}, 422),
        ({"zone_id": "LAO.1_1", "lang": ""}, 422),
        ({"zone_id": "LAO.1_1", "lang": 5}, 422),
        ({"zone_id": "LAO.1_1", "lang": None}, 422),
        ({"zone_id": "LAO.99_1"}, 422),  # unknown zone
        ({"zone_id": "KHM.1_1", "country": "laos"}, 422),  # other country
        ({"zone_id": "LAO.1_1", "country": "narnia"}, 404),
        ({"zone_id": "LAO.1_1", "country": ""}, 422),
        ({"zone_id": "LAO.1_1", "country": 5}, 422),
        ({"zone_id": "LAO.1_1", "country": None}, 422),
    ]
    for payload, want in cases:
        exc = explain_exc(payload, db_path=db, cached_dir=tmp_path)
        assert exc.status_code == want, payload
    exc = explain_exc({"zone_id": "LAO.1_1"},
                      db_path=tmp_path / "missing.db", cached_dir=tmp_path)
    assert exc.status_code == 503


def test_explain_traversal_rejected(tmp_path):
    db = make_db(tmp_path)
    cached_dir = tmp_path / "cache"
    cached_dir.mkdir()
    sentinel = tmp_path / "secret.json"
    sentinel.write_text('{"explanation": "SENTINEL"}', encoding="utf-8")
    bad_zones = ["../LAO.1_1", "LAO.1_1/../../x", "..\\x", "/etc/passwd",
                 "LAO.1_1%2f..", "LAO.1_1\x00", "LAO.1_1 ", "..\\..\\secret"]
    for zone_id in bad_zones:
        exc = explain_exc({"zone_id": zone_id}, db_path=db,
                          cached_dir=cached_dir)
        assert exc.status_code == 422, zone_id
    exc = explain_exc({"zone_id": "LAO.1_1", "lang": "../en"},
                      db_path=db, cached_dir=cached_dir)
    assert exc.status_code == 422
    # Country is never a filesystem path: traversal shapes are 422, not 500.
    for country in ("LAOS", "../countries/laos", "..\\countries\\laos",
                    "C:/clearfield/countries/laos", "laos.json"):
        exc = explain_exc({"zone_id": "LAO.1_1", "country": country},
                          db_path=db, cached_dir=cached_dir)
        assert exc.status_code == 422, country
    assert sentinel.read_text(encoding="utf-8") == '{"explanation": "SENTINEL"}'


def test_explain_wrapper_delegates(monkeypatch):
    # The ASGI wrapper must pass the body through (old zero-arg form is gone).
    monkeypatch.setattr("backend.app.main.explain_request",
                        lambda payload: {"echo": payload})
    assert explain({"zone_id": "LAO.1_1"}) == {"echo": {"zone_id": "LAO.1_1"}}






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
