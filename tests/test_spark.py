"""Tests for agent/spark.py prompt contract (no network, no real key)."""

from agent import spark


ROW = {"id": "LAO.18_1", "admin_name": "Xiangkhoang", "country": "laos",
       "strike_density": None, "crater_evidence": None, "exposure": 1.26,
       "building_density": 5.48, "surveyed_status": "unsurveyed",
       "priority_score": None, "priority_rank": None, "scored_at": None}


def test_prompt_embeds_only_stored_facts_and_missing_rule():
    system, user = spark.build_explain_prompt(ROW, "en")
    assert "1.26" in user and "5.48" in user and "Xiangkhoang" in user
    assert "null" in user  # missing components are explicit in FACTS
    assert "MISSING" in system and "never invent" in system.lower()
    assert "cannot be officially ranked" in system


def test_prompt_language_names():
    assert "Lao" in spark.build_explain_prompt(ROW, "lo")[0]
    assert "Khmer" in spark.build_explain_prompt(ROW, "km")[0]


def test_explain_zone_uses_key_and_returns_text(monkeypatch):
    seen = {}

    def fake_post(system, user, key):
        seen.update(system=system, user=user, key=key)
        return "Zone text."

    monkeypatch.setattr(spark, "_api_key", lambda: "test-key")
    monkeypatch.setattr(spark, "_post_responses", fake_post)
    assert spark.explain_zone(ROW, "en") == "Zone text."
    assert seen["key"] == "test-key"


def test_explain_zone_requires_key(monkeypatch):
    monkeypatch.setattr(spark, "_api_key", lambda: "")
    try:
        spark.explain_zone(ROW, "en")
    except RuntimeError as e:
        assert "META_API_KEY" in str(e)
    else:
        raise AssertionError("expected RuntimeError without a key")
