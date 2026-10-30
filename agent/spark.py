"""Spark explanation voice (Muse Spark via the Meta Model API).

One job: turn a zone's *stored* score components into a plain-language
briefing in English, Lao, Khmer, or Vietnamese. Spark never invents
numbers: build_explain_prompt embeds the DB row as a FACTS JSON block
and the system prompt forbids any value not in it. A missing component
is stated as missing (the zone is then unscorable by design), never
imputed. Live output is never written into demo/cached-responses/ —
that cache stays template-seeded and validated; this is the fallback
for cache misses only (backend/app/main.py explain_request).

Key: META_API_KEY from the environment, else the repo-root .env
(gitignored). Never logged, never returned.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.meta.ai/v1/responses"
MODEL = "muse-spark-1.3"
LANG_NAMES = {"en": "English", "lo": "Lao", "km": "Khmer", "vi": "Vietnamese"}
COMPONENT_LABELS = {
    "strike_density": "THOR strike records per km2 (historical mission targets, 1965-1975)",
    "crater_evidence": "bomb-crater evidence per km2 (KH-9 satellite imagery predictions)",
    "exposure": "exposure features per km2 (OpenStreetMap buildings, settlements, schools, roads, farmland)",
}


def _api_key() -> str:
    key = os.environ.get("META_API_KEY", "").strip()
    if key:
        return key
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("META_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def build_explain_prompt(zone: dict, lang: str = "en") -> tuple[str, str]:
    """(system, user) for one zone row; pure and unit-testable."""
    language = LANG_NAMES.get(lang, "English")
    facts = {
        "zone_id": zone.get("id"),
        "admin_name": zone.get("admin_name"),
        "country": zone.get("country"),
        "score_components": {
            COMPONENT_LABELS[f]: zone.get(f)
            for f in ("strike_density", "crater_evidence", "exposure")
        },
        "building_density_per_km2": zone.get("building_density"),
        "surveyed_status": zone.get("surveyed_status"),
        "priority_score": zone.get("priority_score"),
        "priority_rank": zone.get("priority_rank"),
        "scored_at": zone.get("scored_at"),
    }
    system = (
        "You are ClearField's explanation voice. ClearField ranks bombed "
        "land for survey priority. Explain one zone's ranking (or why it "
        "cannot be ranked) to a local official in plain language.\n"
        "Rules:\n"
        "- Use ONLY the numbers in the FACTS block. Never invent, round "
        "in a way that changes meaning, or import outside knowledge.\n"
        "- A component with value null is MISSING. Say it is missing and "
        "that the zone cannot be officially ranked until it exists. "
        "Missing is not zero and not safe.\n"
        "- Strike records are historical intended targets (1965-1975), "
        "not verified impacts and not present-day danger by themselves.\n"
        "- Crater evidence counts detected bomb craters from 1970s KH-9 "
        "photos; it is evidence of bombing, not a count of live bombs.\n"
        "- Surveyed status changes priority (surveyed x0.25, cleared x0) "
        "but never changes the hazard evidence itself.\n"
        "- Never advise approaching a suspected explosive item. If the "
        "zone is ranked, end with the recommended next step being "
        "non-technical survey by an accredited team.\n"
        f"- Write 3-5 short sentences in {language}. No preamble, no "
        "markdown, no bullet list."
    )
    user = f"FACTS (JSON):\n{json.dumps(facts, ensure_ascii=False)}\n\nExplain this zone."
    return system, user


def _post_responses(system: str, user: str, key: str) -> str:
    payload = {
        "model": MODEL,
        "instructions": system,
        "input": [{"type": "message", "role": "user",
                   "content": [{"type": "input_text", "text": user}]}],
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            doc = json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Meta API HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"Meta API unreachable: {e}") from e
    if isinstance(doc.get("output_text"), str) and doc["output_text"].strip():
        return doc["output_text"].strip()
    texts = []
    for item in doc.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                texts.append(part["text"])
    text = "\n".join(texts).strip()
    if not text:
        raise RuntimeError("Meta API returned no output_text for the explanation")
    return text


def explain_zone(zone: dict, lang: str = "en") -> str:
    """Live Spark explanation for one stored zone row (see module docs)."""
    key = _api_key()
    if not key:
        raise RuntimeError("META_API_KEY not set: Spark explanation unavailable")
    system, user = build_explain_prompt(zone, lang)
    return _post_responses(system, user, key)
