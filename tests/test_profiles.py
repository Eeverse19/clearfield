from backend.app.profiles import REQUIRED_FIELDS, list_countries, load_country


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
