import json
import re

import pytest

from backend.app.config import REPO_ROOT
from backend.app.profiles import REQUIRED_FIELDS, list_countries, load_country

GADM_DIR = REPO_ROOT / "data" / "gadm"
ZONE_ID_RE = re.compile(r"^[A-Z]{3}\.\d+_1$")


def test_demo_countries_load():
    ids = {p["id"] for p in list_countries()}
    assert {"laos", "cambodia"} <= ids


def test_required_fields_present():
    for profile in list_countries():
        for field in REQUIRED_FIELDS:
            assert field in profile, f"{profile['id']} missing {field}"


def test_laos_and_cambodia_demo_areas():
    # GADM admin_name for LAO.18_1.
    assert load_country("laos")["demo_area"] == "Xiangkhoang"
    # Owner-confirmed 2026-10-27. GADM admin_name is TbongKhmum (KHM.25_1).
    assert load_country("cambodia")["demo_area"] == "Tbong Khmum"


def test_demo_zone_ids():
    # demo_area is a display name (may differ from zones.admin_name, e.g.
    # "Tbong Khmum" vs GADM "TbongKhmum"); demo_zone_id is the join key.
    assert load_country("laos")["demo_zone_id"] == "LAO.18_1"
    assert load_country("cambodia")["demo_zone_id"] == "KHM.25_1"
    assert load_country("vietnam")["demo_zone_id"] is None
    for profile in list_countries():
        zone_id = profile["demo_zone_id"]
        assert zone_id is None or ZONE_ID_RE.match(zone_id), (
            f"{profile['id']} demo_zone_id {zone_id!r} is not a GADM GID_1"
        )
        assert (profile["demo_area"] is None) == (zone_id is None)


@pytest.mark.skipif(
    not list(GADM_DIR.glob("gadm41_*_1.json")),
    reason="real data/gadm/*.json absent (gitignored; not in fresh clones)",
)
def test_demo_zone_ids_exist_in_gadm():
    # zones.id values come from GADM GID_1 (scripts/seed_db.py), so a
    # demo_zone_id that is not a GID_1 of its own country joins nothing.
    for profile in list_countries():
        zone_id = profile["demo_zone_id"]
        if zone_id is None:
            continue
        code = profile["boundaries"]["country_code"]
        level = profile["boundaries"].get("admin_level", 1)
        path = GADM_DIR / f"gadm41_{code}_{level}.json"
        if not path.exists():
            pytest.skip(f"GADM file absent: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        gids = {f["properties"]["GID_1"] for f in data["features"]}
        assert zone_id in gids, f"{profile['id']} demo_zone_id {zone_id} not in {path.name}"
