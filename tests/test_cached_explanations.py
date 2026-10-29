"""Seeded demo/cached-responses/explain-*.json must match the live DB.

Every committed cache file is checked against the current stored row:
filename grammar, frozen schema fields, exact score_components, and —
critically — the explanation text itself, which must equal the frozen
template rendered from that row (shared render_explanation). A re-score
or a zone rename without re-running scripts/make_cached_explanations.py
fails here instead of silently serving stale text.
"""

import json

import pytest

from backend.app import config
from backend.app.db import get_conn
from backend.app.main import (EXPLAIN_COMPONENT_FIELDS, EXPLAIN_FILE_FIELDS,
                              EXPLAIN_GENERATED_FROM, EXPLAIN_ORIGIN,
                              explain_request, render_explanation)

DB = config.LOCAL_DB_PATH
CACHE_DIR = config.CACHED_RESPONSES_DIR

pytestmark = pytest.mark.skipif(not DB.exists(),
                                reason="real seeded DB not present")

COLUMNS = ("id, country, admin_name, strike_density, crater_evidence, "
           "exposure, surveyed_status, priority_score, priority_rank, "
           "scored_at")


def ranked_rows():
    conn = get_conn(readonly=True)  # mode=ro, Windows long-path safe
    try:
        return {r["id"]: dict(r) for r in conn.execute(
            f"SELECT {COLUMNS} FROM zones WHERE priority_rank IS NOT NULL")}
    finally:
        conn.close()


def cache_files():
    return sorted(CACHE_DIR.glob("explain-*.json"))


def test_every_ranked_zone_has_en_file_and_no_extras():
    rows = ranked_rows()
    assert rows, "expected ranked zones in the seeded DB"
    names = {p.name for p in cache_files()}
    assert names == {f"explain-{zone_id}-en.json" for zone_id in rows}


def test_cache_files_match_db_exactly():
    rows = ranked_rows()
    for path in cache_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data) == set(EXPLAIN_FILE_FIELDS), path.name
        assert data["schema_version"] == 1 and data["kind"] == "explain"
        assert data["origin"] == EXPLAIN_ORIGIN
        assert data["generated_from"] == EXPLAIN_GENERATED_FROM
        assert path.name == f"explain-{data['zone_id']}-{data['lang']}.json"
        row = rows[data["zone_id"]]
        assert data["country"] == row["country"]
        assert data["admin_name"] == row["admin_name"]
        assert data["score_components"] == {
            f: row[f] for f in EXPLAIN_COMPONENT_FIELDS}
        # Text is verified, not trusted (critic defect 4).
        assert data["explanation"] == render_explanation(row), path.name


def test_seeded_zone_serves_ungarbled_text_no_key(monkeypatch):
    monkeypatch.setattr(config, "META_API_KEY", "")
    out = explain_request({"zone_id": "LAO.17_1", "lang": "km"})
    assert out["lang"] == "en" and out["requested_lang"] == "km"
    # cp1252 mojibake guard (critic defect 2): real name and unit survive.
    assert "Xékong" in out["explanation"] and "km²" in out["explanation"]
    assert "XÃ©kong" not in out["explanation"]
