import math
import sqlite3
from pathlib import Path

import pytest

from pipelines.scoring import normalize_components, rank_zones, score_country, score_zone

SCHEMA = Path(__file__).resolve().parents[1] / "db" / "schema.local.sql"


def zone(zid, strike=1.0, crater=1.0, exposure=1.0, status="unsurveyed"):
    return {"id": zid, "strike_density": strike, "crater_evidence": crater,
            "exposure": exposure, "surveyed_status": status}


def test_deterministic_exact_product():
    for _ in range(100):
        assert score_zone(strike_density=0.5, crater_evidence=0.5, exposure=0.5,
                          surveyed_status="unsurveyed") == 0.125
    assert score_zone(strike_density=1, crater_evidence=1, exposure=1,
                      surveyed_status="unsurveyed") == 1.0


def test_surveyed_factor():
    full = dict(strike_density=1.0, crater_evidence=1.0, exposure=1.0)
    assert score_zone(**full, surveyed_status="surveyed") == 0.25
    assert score_zone(**full, surveyed_status="cleared") == 0.0


def test_none_propagates_never_zero():
    base = dict(strike_density=1.0, crater_evidence=1.0, exposure=1.0,
                surveyed_status="unsurveyed")
    for key in ("strike_density", "crater_evidence", "exposure"):
        assert score_zone(**{**base, key: None}) is None
    assert score_zone(strike_density=None, crater_evidence=None, exposure=None,
                      surveyed_status="unsurveyed") is None


def test_validation():
    base = dict(strike_density=0.5, crater_evidence=0.5, exposure=0.5,
                surveyed_status="unsurveyed")
    for bad in (-0.1, 1.1, math.nan, math.inf, "high"):
        with pytest.raises(ValueError):
            score_zone(**{**base, "strike_density": bad})
    with pytest.raises(ValueError):
        score_zone(**{**base, "surveyed_status": "bogus"})


def test_normalization_log1p_country_max():
    rows = [zone("a", strike=0.0), zone("b", strike=3.0), zone("c", strike=8.0)]
    out = normalize_components(rows)
    assert out[0]["strike_density"] == 0.0
    assert out[2]["strike_density"] == 1.0
    assert out[1]["strike_density"] == pytest.approx(math.log1p(3) / math.log1p(8))
    # Raw rows are never mutated.
    assert rows[1]["strike_density"] == 3.0


def test_normalization_all_zero_and_all_equal_and_null_excluded():
    assert all(r["exposure"] == 0.0 for r in normalize_components(
        [zone("a", exposure=0.0), zone("b", exposure=0.0)]))
    assert all(r["exposure"] == 1.0 for r in normalize_components(
        [zone("a", exposure=2.0), zone("b", exposure=2.0)]))
    out = normalize_components([zone("a", exposure=None), zone("b", exposure=4.0)])
    assert out[0]["exposure"] is None and out[1]["exposure"] == 1.0
    with pytest.raises(ValueError):
        normalize_components([zone("a", strike=-1.0)])


def test_rank_tiebreak_and_unscorable():
    rows = [zone("b", strike=2.0), zone("a", strike=2.0), zone("z", strike=None),
            zone("c", strike=9.0, status="cleared")]
    ranked = rank_zones(rows)
    # a/b tie on everything -> id asc; cleared scores a real 0.0, ranked last.
    assert ranked["a"][1] == 1 and ranked["b"][1] == 2
    assert ranked["c"] == (0.0, 3)
    assert ranked["z"] == (None, None)


def make_db(tmp_path, rows):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO zones (id, country, strike_density, crater_evidence, exposure,"
        " surveyed_status) VALUES (:id, :country, :strike_density, :crater_evidence,"
        " :exposure, :surveyed_status)",
        [dict(country="laos", **r) for r in rows])
    conn.commit()
    conn.close()
    return path


def read_zones(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM zones ORDER BY id")]
    conn.close()
    return rows


def test_runner_writes_scores_and_is_idempotent(tmp_path):
    rows = [zone("a", strike=8.0), zone("b", strike=1.0), zone("c", strike=None)]
    path = make_db(tmp_path, rows)
    summary = score_country("laos", db_path=path, now="2026-10-26T00:00:00+00:00")
    assert summary == {"country": "laos", "zones": 3, "scored": 2, "unscored": 1,
                       "null_components": {"strike_density": 1, "crater_evidence": 0, "exposure": 0}}
    first = read_zones(path)
    by_id = {r["id"]: r for r in first}
    assert by_id["a"]["priority_rank"] == 1 and by_id["b"]["priority_rank"] == 2
    assert by_id["c"]["priority_score"] is None and by_id["c"]["priority_rank"] is None
    assert all(r["scored_at"] == "2026-10-26T00:00:00+00:00" for r in first)
    # Components untouched by scoring.
    assert by_id["a"]["strike_density"] == 8.0
    score_country("laos", db_path=path, now="2026-10-26T01:00:00+00:00")
    second = read_zones(path)
    strip = lambda rs: [{k: v for k, v in r.items() if k != "scored_at"} for r in rs]
    assert strip(first) == strip(second)


def test_runner_scores_zero_on_todays_db_shape(tmp_path):
    # Strike + exposure all NULL (real DB today): 0 scored is correct, not an error.
    rows = [zone("a", strike=None, exposure=None), zone("b", strike=None, exposure=None)]
    path = make_db(tmp_path, rows)
    summary = score_country("laos", db_path=path, now="2026-10-26T00:00:00+00:00")
    assert summary["scored"] == 0 and summary["unscored"] == 2
    assert all(r["priority_rank"] is None for r in read_zones(path))
