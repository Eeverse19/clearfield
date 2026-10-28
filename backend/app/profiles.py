"""Country profile loading. Country is configuration, never code."""

import json

from backend.app.config import COUNTRIES_DIR

REQUIRED_FIELDS = (
    "id",
    "name",
    "languages",
    "demo_area",
    "demo_zone_id",
    "strike_source",
    "imagery",
    "boundaries",
    "osm_extract",
    "stats_source",
)


def list_countries() -> list[dict]:
    return [load_country(p.stem) for p in sorted(COUNTRIES_DIR.glob("*.json"))]


def load_country(country_id: str) -> dict:
    path = COUNTRIES_DIR / f"{country_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"no country profile: {path}")
    profile = json.loads(path.read_text(encoding="utf-8"))
    missing = [f for f in REQUIRED_FIELDS if f not in profile]
    if missing:
        raise ValueError(f"{path.name} missing required fields: {missing}")
    if profile["id"] != country_id:
        raise ValueError(f"{path.name} id {profile['id']!r} != filename {country_id!r}")
    strike_source = profile["strike_source"]
    country_filter = strike_source.get("country_filter") if isinstance(strike_source, dict) else None
    if (not isinstance(country_filter, list) or not country_filter
            or not all(isinstance(value, str) for value in country_filter)):
        raise ValueError(
            f"{path.name} strike_source.country_filter must be a non-empty "
            f"list of strings, got {country_filter!r}")
    return profile
