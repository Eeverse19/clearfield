import json
import re

import pytest

import backend.app.profiles as profiles_mod
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


def test_thor_dataset_and_country_filter_lists():
    # docs/thor/thor_final_spec.md §3: one shared THOR file; country_filter
    # is a list of exact TgtCountry values (cross-check only, never a filter).
    for profile in list_countries():
        dataset = profile["strike_source"]["dataset"]
        assert dataset.endswith("THOR_Vietnam_7_31_2013.csv"), profile["id"]
        country_filter = profile["strike_source"]["country_filter"]
        assert isinstance(country_filter, list) and country_filter
        assert all(isinstance(v, str) for v in country_filter)
    assert load_country("laos")["strike_source"]["country_filter"] == ["LAOS"]
    assert load_country("cambodia")["strike_source"]["country_filter"] == ["CAMBODIA"]
    assert load_country("vietnam")["strike_source"]["country_filter"] == [
        "SOUTH VIETNAM", "NORTH VIETNAM"]


@pytest.mark.parametrize("bad_filter", ["LAOS", [], ["LAOS", 3], None])
def test_string_country_filter_rejected(tmp_path, monkeypatch, bad_filter):
    # A string filter iterates per-character downstream; load_country must
    # refuse it (and every other non-(non-empty list[str]) shape).
    profile = load_country("laos")
    profile["strike_source"] = dict(profile["strike_source"],
                                     country_filter=bad_filter)
    (tmp_path / "laos.json").write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(profiles_mod, "COUNTRIES_DIR", tmp_path)
    with pytest.raises(ValueError, match="country_filter"):
        load_country("laos")


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
