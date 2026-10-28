"""Deterministic priority scoring (plain code; models never write scores).

Contract (WORKFLOW_SYNTHESIS.md section 2):
- score_zone takes components already normalized to [0,1]; any component
  None -> None (unscorable, never an imputed 0); out-of-range/NaN/inf or an
  unknown surveyed_status -> ValueError.
- "Minus already-surveyed status" is the multiplicative SURVEYED_FACTOR.
  Its values are a PROVISIONAL default (synthesis U2), not a doc-pinned
  constant: change them in this one place, with the tests, when the owner
  freezes surveyed handling. Nothing writes surveyed/cleared yet.
- The runner normalizes raw stored components per country as
  log1p(x)/log1p(country max) (max 0 -> 0.0), ranks 1..N per country with
  tie-break score DESC, raw components DESC, id ASC, and is the ONLY writer
  of priority_score/priority_rank/scored_at. Components are never mutated.
- THOR strike_density is seeded on 106/106 zones and OSM exposure has
  landed for laos and cambodia, but most zones are still unscorable for
  lack of crater_evidence (vietnam also still lacks exposure): while any
  component is NULL, a correct run leaves that zone unscored and says so.
"""

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `python pipelines/scoring.py`

COMPONENTS = ("strike_density", "crater_evidence", "exposure")
SURVEYED_FACTOR = {"unsurveyed": 1.0, "surveyed": 0.25, "cleared": 0.0}


def score_zone(*, strike_density, crater_evidence, exposure, surveyed_status):
    if surveyed_status not in SURVEYED_FACTOR:
        raise ValueError(f"unknown surveyed_status: {surveyed_status!r}")
    values = (strike_density, crater_evidence, exposure)
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise ValueError(f"normalized component must be a finite real in [0,1], got {v!r}")
    if any(v is None for v in values):
        return None
    return float(strike_density * crater_evidence * exposure * SURVEYED_FACTOR[surveyed_status])


def normalize_components(rows: list[dict]) -> list[dict]:
    """Return copies of rows with each raw component normalized to [0,1]."""
    out = [dict(r) for r in rows]
    for comp in COMPONENTS:
        raw = []
        for r in rows:
            v = r[comp]
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(v) or v < 0:
                raise ValueError(f"raw {comp} must be a finite real >= 0, got {v!r}")
            raw.append(v)
        denom = math.log1p(max(raw)) if raw else 0.0
        for r in out:
            if r[comp] is not None:
                r[comp] = math.log1p(r[comp]) / denom if denom > 0 else 0.0
    return out


def rank_zones(rows: list[dict]) -> dict[str, tuple]:
    """{zone id: (score, rank)}; rank/score None for unscorable zones."""
    normalized = normalize_components(rows)
    scored = []
    result: dict[str, tuple] = {}
    for raw, norm in zip(rows, normalized):
        score = score_zone(strike_density=norm["strike_density"],
                           crater_evidence=norm["crater_evidence"],
                           exposure=norm["exposure"],
                           surveyed_status=raw["surveyed_status"])
        if score is None:
            result[raw["id"]] = (None, None)
        else:
            scored.append((score, raw))
    scored.sort(key=lambda t: (-t[0], -t[1]["strike_density"], -t[1]["crater_evidence"],
                               -t[1]["exposure"], t[1]["id"]))
    for i, (score, raw) in enumerate(scored, start=1):
        result[raw["id"]] = (score, i)
    return result


def score_country(country_id: str, db_path=None, now: str | None = None) -> dict:
    from backend.app.db import get_conn

    now = now or datetime.now(timezone.utc).isoformat()
    conn = get_conn(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, strike_density, crater_evidence, exposure, surveyed_status"
            " FROM zones WHERE country = ?", (country_id,))]
        ranked = rank_zones(rows)
        with conn:
            conn.executemany(
                "UPDATE zones SET priority_score = ?, priority_rank = ?, scored_at = ?"
                " WHERE id = ?",
                [(s, r, now, zid) for zid, (s, r) in ranked.items()])
    finally:
        conn.close()
    scored_n = sum(1 for s, _ in ranked.values() if s is not None)
    return {
        "country": country_id,
        "zones": len(rows),
        "scored": scored_n,
        "unscored": len(rows) - scored_n,
        "null_components": {c: sum(1 for r in rows if r[c] is None) for c in COMPONENTS},
    }


if __name__ == "__main__":
    from pipelines._profile import country_arg

    profile = country_arg()
    summary = score_country(profile["id"])
    print(f"[scoring] {summary['country']}: {summary['scored']}/{summary['zones']} zones scored, "
          f"{summary['unscored']} unscored (NULL components: {summary['null_components']})")
    if summary["scored"] == 0 and summary["zones"]:
        print("[scoring] 0 scored is expected while a component is NULL "
              "(see NULL-component counts above: a NULL component means "
              "unscorable, never an imputed 0).")
