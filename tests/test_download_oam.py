"""Unit tests for scripts/download_oam.py gates (no network).

The download gate is the license boundary: only per-image CC-BY 4.0
pockets at or under the size cap may download; everything else stays
catalog-only. These pin that it fails closed.
"""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "download_oam",
    Path(__file__).resolve().parents[1] / "scripts" / "download_oam.py",
)
oam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oam)

CAP = 250_000_000


def _rec(license="CC-BY 4.0", file_size=1000):
    return {"properties": {"license": license}, "file_size": file_size}


def test_download_decision_allows_cc_by_under_cap():
    assert oam.download_decision(_rec(), CAP) == (True, "ok")
    # Exactly at the cap still downloads (cap is inclusive).
    assert oam.download_decision(_rec(file_size=CAP), CAP) == (True, "ok")


def test_download_decision_rejects_other_licenses():
    for lic in ["CC BY-SA 4.0", "CC-BY-NC 4.0", "cc-by 4.0", "CC-BY 4.0 ", ""]:
        ok, reason = oam.download_decision(_rec(license=lic), CAP)
        assert not ok, lic
        assert reason.startswith("license")
    # Missing properties/license must not fall through to a download.
    ok, _reason = oam.download_decision({"file_size": 1000}, CAP)
    assert not ok
    ok, _reason = oam.download_decision(
        {"properties": None, "file_size": 1000}, CAP)
    assert not ok


def test_download_decision_rejects_over_cap():
    ok, reason = oam.download_decision(_rec(file_size=CAP + 1), CAP)
    assert not ok
    assert "file_size" in reason


def test_record_centre_is_lon_lat():
    # bbox is [minlon, minlat, maxlon, maxlat]; centre keeps that order.
    assert oam.record_centre({"bbox": [102.0, 10.0, 106.0, 14.0]}) == (104.0, 12.0)
