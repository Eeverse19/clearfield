"""Spark query/explain/report entry point. Scaffold stub (needs META_API_KEY)."""

import os


def explain_zone(zone: dict, lang: str = "en") -> str:
    if not os.environ.get("META_API_KEY"):
        raise RuntimeError("META_API_KEY not set: Spark explanation unavailable")
    raise NotImplementedError("Spark agent not wired yet (cache-first path lands first)")
