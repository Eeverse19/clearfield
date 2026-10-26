from backend.app.profiles import REQUIRED_FIELDS, list_countries, load_country


def test_demo_countries_load():
    ids = {p["id"] for p in list_countries()}
    assert {"laos", "cambodia"} <= ids


def test_required_fields_present():
    for profile in list_countries():
        for field in REQUIRED_FIELDS:
            assert field in profile, f"{profile['id']} missing {field}"


def test_laos_demo_area_and_cambodia_pending():
    assert load_country("laos")["demo_area"] == "Xieng Khouang"
    # Cambodia's demo province is picked from THOR density once data exists.
    assert load_country("cambodia")["demo_area"] is None
