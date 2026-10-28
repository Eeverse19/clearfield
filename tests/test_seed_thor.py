"""THOR strike_density seed tests (docs/thor/thor_final_spec.md §6 + §9.5).

Fixture DBs are built from db/schema.local.sql in tmp_path with 4 square
zones; fixture CSVs carry only the 5 required counting columns plus
NumWeaponsDelivered/WeaponType. Fixtures are synthetic WGS84, so tests
inject the identity datum transform except where the transform itself is
under test. Expected areas are recomputed here with Geod, never copied
from the implementation's output.
"""

import csv
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from pyproj import Geod
from shapely.geometry import MultiPolygon, box, mapping

_spec = importlib.util.spec_from_file_location(
    "seed_thor",
    Path(__file__).resolve().parents[1] / "scripts" / "seed_thor.py",
)
thor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(thor)

SCHEMA = Path(__file__).resolve().parents[1] / "db" / "schema.local.sql"
GEOD = Geod(ellps="WGS84")
IDENTITY = lambda lon, lat: (lon, lat)  # noqa: E731

ZONES = [
    ("VNM.1_1", "vietnam", box(106, 16, 107, 17)),
    ("VNM.2_1", "vietnam", box(107, 16, 108, 17)),  # shares edge x=107
    ("LAO.1_1", "laos", box(102, 17, 103, 18)),
    ("KHM.1_1", "cambodia", box(104, 11, 105, 12)),
]

CSV_HEADER = ["SourceRecord", "MSNDate", "TgtCountry",
              "TgtLatDD_DDD_WGS84", "TgtLonDDD_DDD_WGS84",
              "NumWeaponsDelivered", "WeaponType"]


def area_km2(geom):
    return abs(GEOD.geometry_area_perimeter(MultiPolygon([geom]))[0]) / 1e6


def make_db(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO zones (id, country, admin_name, geom, crater_evidence,"
        " exposure, surveyed_status, priority_score, priority_rank, scored_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(zid, country, f"name-{zid}",
          json.dumps(mapping(MultiPolygon([geom]))),
          1.5, 2.5, "surveyed", 0.9, 1, "2026-01-01T00:00:00+00:00")
         for zid, country, geom in ZONES])
    conn.execute(
        "INSERT INTO finds (id, country, zone_id, object_type)"
        " VALUES ('find-1', 'laos', 'LAO.1_1', 'bomblet')")
    conn.execute(
        "INSERT INTO craters (id, country, source) VALUES ('cr-1', 'laos', 'x')")
    conn.commit()
    conn.close()
    return path


def read_zones(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM zones ORDER BY id")]
    conn.close()
    return {r["id"]: r for r in rows}


def row(lon, lat, tgt="LAOS", source="SEADAB", date="19700101",
        weapons="10", wtype="MK82"):
    return [source, date, tgt, str(lat), str(lon), weapons, wtype]


def write_csv(tmp_path, rows, header=CSV_HEADER, name="thor.csv"):
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def run(tmp_path, rows, **kw):
    kw.setdefault("datum_transform", IDENTITY)
    db = make_db(tmp_path)
    result = thor.seed_thor(csv_path=write_csv(tmp_path, rows), db_path=db, **kw)
    return db, result


def assert_identity(r):
    assert r["rows_read"] == (
        r["assigned"] + r["invalid_coords"] + r["outside_zones"]
        + r["outside_scope"] + r["deduped_saccoact"] + r["weapon_excluded"])
    assert r["assigned"] == sum(r["missions"].values())


# --- §6 tests 1-12 -----------------------------------------------------------

def test_density_is_missions_per_geodesic_km2(tmp_path):
    rows = [row(102.4, 17.4), row(102.6, 17.6), row(102.5, 17.5)]
    db, r = run(tmp_path, rows)
    expected = 3 / area_km2(box(102, 17, 103, 18))
    zones = read_zones(db)
    assert zones["LAO.1_1"]["strike_density"] == pytest.approx(expected)
    assert r["densities"]["LAO.1_1"] == pytest.approx(expected)
    assert r["assigned"] == 3 and r["missions"]["LAO.1_1"] == 3
    assert r["zones_written"] == 4 and r["integrity"] == "ok"
    assert r["null_strike_density_in_scope"] == 0
    assert_identity(r)


def test_null_literal_empty_and_junk_coords_invalid(tmp_path):
    rows = [
        row("NULL", 17.5),            # lon NULL literal
        row(102.5, "null"),           # lat null literal, lowercase
        row("", 17.5),                # empty
        row(102.5, ""),               # empty
        row("garbage", 17.5),         # unparseable
        row(102.5, "NaN"),            # unparseable (NaN)
        row("inf", 17.5),             # unparseable (inf)
        row(102.5, 17.5),             # the one valid row
    ]
    db, r = run(tmp_path, rows)
    assert r["rows_read"] == 8 and r["assigned"] == 1
    assert r["invalid_coords"] == 7
    assert r["invalid_reasons"] == {
        "empty": 2, "null_literal": 2, "unparseable": 3,
        "out_of_range": 0, "zero_zero": 0}
    assert_identity(r)


def test_zero_zero_and_out_of_range_invalid(tmp_path):
    rows = [
        row(0, 0), row("-0.0", "0.0"),          # zero_zero x2
        row(102.5, 91), row(181, 17.5), row(102.5, -90.5),  # out_of_range x3
        row(102.5, 17.5),                        # valid
    ]
    db, r = run(tmp_path, rows)
    assert r["assigned"] == 1 and r["invalid_coords"] == 5
    assert r["invalid_reasons"]["zero_zero"] == 2
    assert r["invalid_reasons"]["out_of_range"] == 3
    assert_identity(r)


def test_minus_one_weapons_still_one_mission(tmp_path):
    rows = [
        row(102.5, 17.5, weapons="-1", wtype=""),
        row(102.5, 17.5, weapons="", wtype="GARBAGE"),
        row(102.5, 17.5, weapons="99999", wtype="MK82"),
    ]
    db, r = run(tmp_path, rows)
    assert r["missions"]["LAO.1_1"] == 3  # each row = exactly 1 mission (U17)
    assert r["weapon_excluded"] == 0
    assert_identity(r)


def test_south_and_north_vietnam_both_assigned_no_filter_drop(tmp_path):
    rows = [
        row(106.5, 16.5, tgt="SOUTH VIETNAM"),
        row(106.5, 16.5, tgt="NORTH VIETNAM"),
        row(107.5, 16.5, tgt="south vietnam"),   # case-insensitive map
        row(107.5, 16.5, tgt=""),                # empty TgtCountry still assigned
        row(107.5, 16.5, tgt="VIETNAM"),         # value absent in real THOR
    ]
    db, r = run(tmp_path, rows)
    assert r["assigned"] == 5
    assert r["missions"]["VNM.1_1"] == 2 and r["missions"]["VNM.2_1"] == 3
    assert r["mismatch"] == 0  # unknown/empty/value-absent are not mismatches
    assert_identity(r)


def test_tgtcountry_mismatch_point_wins_and_is_counted(tmp_path):
    rows = [
        row(102.5, 17.5, tgt="SOUTH VIETNAM"),  # point in laos zone
        row(106.5, 16.5, tgt="LAOS"),           # point in vietnam zone
        row(102.5, 17.5, tgt="LAOS"),           # agrees
    ]
    db, r = run(tmp_path, rows)
    assert r["missions"]["LAO.1_1"] == 2 and r["missions"]["VNM.1_1"] == 1
    assert r["mismatch"] == 2
    assert r["mismatch_matrix"] == {"SOUTH VIETNAM->laos": 1, "LAOS->vietnam": 1}
    assert len(r["mismatch_examples"]) == 2
    assert r["mismatch_examples"][0][1:3] == ("SOUTH VIETNAM", "LAO.1_1")
    assert_identity(r)


def test_boundary_point_assigned_once_smallest_zone_id(tmp_path):
    rows = [row(107, 16.5, tgt="SOUTH VIETNAM")]  # on the shared VNM edge
    db, r = run(tmp_path, rows)
    assert r["assigned"] == 1 and r["multi_hit"] == 1
    assert r["missions"]["VNM.1_1"] == 1 and r["missions"]["VNM.2_1"] == 0
    assert_identity(r)


def test_outside_and_thailand_reconciles(tmp_path):
    rows = [
        row(99.0, 15.0, tgt="THAILAND"),   # outside all zones
        row(120.0, 30.0, tgt="LAOS"),      # outside; no mismatch (unassigned)
        row(99.0, 15.0, tgt=""),           # outside
        row(102.5, 17.5, tgt="THAILAND"),  # inside laos; thailand != mismatch
    ]
    db, r = run(tmp_path, rows)
    assert r["outside_zones"] == 3 and r["assigned"] == 1
    assert r["mismatch"] == 0
    assert r["missions"]["LAO.1_1"] == 1
    assert_identity(r)


def test_only_strike_density_column_written(tmp_path):
    db = make_db(tmp_path)
    before = read_zones(db)
    conn = sqlite3.connect(db)
    finds_before = conn.execute("SELECT * FROM finds").fetchall()
    craters_before = conn.execute("SELECT * FROM craters").fetchall()
    conn.close()
    rows = [row(102.5, 17.5)]  # only LAO gets a mission; KHM stays zero
    r = thor.seed_thor(csv_path=write_csv(tmp_path, rows), db_path=db,
                       datum_transform=IDENTITY)
    after = read_zones(db)
    for zid, zbefore in before.items():
        for col, value in zbefore.items():
            if col != "strike_density":
                assert after[zid][col] == value, f"{zid}.{col} changed"
    assert after["LAO.1_1"]["strike_density"] > 0
    assert after["KHM.1_1"]["strike_density"] == 0.0  # zero missions -> 0.0
    assert after["KHM.1_1"]["strike_density"] is not None
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT * FROM finds").fetchall() == finds_before
    assert conn.execute("SELECT * FROM craters").fetchall() == craters_before
    conn.close()
    assert_identity(r)


def test_second_run_idempotent(tmp_path):
    rows = [row(102.5, 17.5), row(106.5, 16.5, tgt="NORTH VIETNAM"),
            row(99.0, 15.0, tgt="THAILAND"), row(0, 0)]
    db = make_db(tmp_path)
    csv_path = write_csv(tmp_path, rows)
    first = thor.seed_thor(csv_path=csv_path, db_path=db, datum_transform=IDENTITY)
    zones_first = read_zones(db)
    second = thor.seed_thor(csv_path=csv_path, db_path=db, datum_transform=IDENTITY)
    assert read_zones(db) == zones_first
    assert second["densities"] == first["densities"]
    assert second["assigned"] == first["assigned"] == 2


def test_missing_csv_and_bad_header_fail_before_write(tmp_path):
    db = make_db(tmp_path)
    with pytest.raises(FileNotFoundError) as excinfo:
        thor.seed_thor(csv_path=tmp_path / "absent.csv", db_path=db,
                       datum_transform=IDENTITY)
    assert thor.EXTRACT_COMMAND in str(excinfo.value)  # exact 7-Zip message
    bad = write_csv(tmp_path, [row(102.5, 17.5)],
                    header=["SourceRecord", "MSNDate", "TgtCountry", "Lat", "Lon",
                            "NumWeaponsDelivered", "WeaponType"], name="bad.csv")
    with pytest.raises(ValueError, match="missing required columns"):
        thor.seed_thor(csv_path=bad, db_path=db, datum_transform=IDENTITY)
    assert all(z["strike_density"] is None for z in read_zones(db).values())
    assert thor.main(["--csv", str(tmp_path / "absent.csv"),
                      "--db", str(db)]) == 1  # CLI maps failure to exit 1
    assert all(z["strike_density"] is None for z in read_zones(db).values())


def test_country_flag_writes_only_that_country(tmp_path):
    rows = [row(102.5, 17.5), row(106.5, 16.5, tgt="NORTH VIETNAM"),
            row(104.5, 11.5, tgt="CAMBODIA")]
    db, r = run(tmp_path, rows, country="laos")
    zones = read_zones(db)
    assert zones["LAO.1_1"]["strike_density"] > 0
    assert zones["VNM.1_1"]["strike_density"] is None
    assert zones["KHM.1_1"]["strike_density"] is None
    assert r["zones"] == 1 and r["zones_written"] == 1
    assert r["assigned"] == 1 and r["outside_scope"] == 2
    assert r["outside_zones"] == 0
    assert_identity(r)


def test_dry_run_writes_nothing(tmp_path):
    rows = [row(102.5, 17.5)]
    db, r = run(tmp_path, rows, dry_run=True)
    assert r["dry_run"] is True and r["zones_written"] == 0
    assert r["densities"]["LAO.1_1"] > 0  # would-write values still reported
    assert all(z["strike_density"] is None for z in read_zones(db).values())
    assert_identity(r)


# --- §9.5 tests 13-16 --------------------------------------------------------

def test_dedup_drops_saccoact_from_19710401_only(tmp_path):
    rows = [
        row(102.5, 17.5, source="SACCOACT", date="19710401"),  # dropped
        row(102.5, 17.5, source="SACCOACT", date="19750331"),  # dropped
        row(102.5, 17.5, source="SACCOACT", date="19710331"),  # kept (pre-cutoff)
        row(102.5, 17.5, source="SEADAB", date="19710401"),    # kept (source)
        row("NULL", 17.5, source="SACCOACT", date="19710401"),  # invalid first
    ]
    db, r = run(tmp_path, rows)
    assert r["deduped_saccoact"] == 2
    # March variant counts every valid SACCOACT row from 19710301 on.
    assert r["deduped_saccoact_march_variant"] == 3
    assert r["missions"]["LAO.1_1"] == 2 and r["assigned"] == 2
    assert r["invalid_coords"] == 1
    assert_identity(r)


def test_default_transform_is_forced_epsg1542():
    transform = thor.make_datum_transform()
    lon, lat = transform(107.0, 16.8)
    assert (lon, lat) == pytest.approx(
        (106.99580732082036, 16.801609276893966), abs=1e-6)
    # Out of EPSG:1542's own area (Vientiane): forcing must still shift —
    # a bare EPSG:4131->4326 transform silently no-ops here.
    lon, lat = transform(102.6, 17.97)
    assert (lon, lat) == pytest.approx(
        (102.5963613440926, 17.97141995372316), abs=1e-6)
    assert (lon, lat) != (102.6, 17.97)


def test_transform_applied_before_assignment(tmp_path):
    shift_east = lambda lon, lat: (lon + 1.0, lat)  # noqa: E731
    rows = [row(106.5, 16.5, tgt="SOUTH VIETNAM")]  # raw in VNM.1, shifted VNM.2
    db, r = run(tmp_path, rows, datum_transform=shift_east)
    assert r["missions"]["VNM.2_1"] == 1 and r["missions"]["VNM.1_1"] == 0
    assert r["baseline_missions"]["VNM.1_1"] == 1  # A uses the raw point
    zones = read_zones(db)
    assert zones["VNM.2_1"]["strike_density"] > 0
    assert zones["VNM.1_1"]["strike_density"] == 0.0
    assert_identity(r)


def test_baseline_and_corrected_counts_reconcile(tmp_path):
    shift_east = lambda lon, lat: (lon + 1.0, lat)  # noqa: E731
    rows = [
        # A: in VNM.1_1; B/C: shifted into VNM.2_1. Assigned in A, B and C.
        row(106.5, 16.5, tgt="SOUTH VIETNAM"),
        # Deduped SACCOACT. A: in LAO.1_1; B: shifted to lon 103.5 (outside);
        # C: dropped. So A counts it, B and C do not.
        row(102.5, 17.5, source="SACCOACT", date="19710401"),
        # SEADAB same target: A in LAO.1_1, B/C shifted outside.
        row(102.5, 17.5, date="19710401"),
        row(0, 0),  # invalid everywhere
    ]
    db, r = run(tmp_path, rows, datum_transform=shift_east)
    assert r["baseline_assigned"] == 3      # A
    assert r["datum_assigned"] == 1         # B
    assert r["assigned"] == 1               # C
    assert r["deduped_saccoact"] == 1 and r["weapon_excluded"] == 0
    # Exact deltas (not the algebraic C-A == (B-A)+(C-B) tautology, which
    # holds by construction for any counters and proves nothing).
    assert r["datum_delta"] == -2 and r["dedup_delta"] == 0
    assert r["assigned"] - r["baseline_assigned"] == -2
    assert_identity(r)


# --- critic-fix regression tests --------------------------------------------

def test_header_only_and_empty_csv_fail_before_write(tmp_path):
    db = make_db(tmp_path)
    with pytest.raises(ValueError, match="no data rows"):
        thor.seed_thor(csv_path=write_csv(tmp_path, []), db_path=db,
                       datum_transform=IDENTITY)
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="empty file"):
        thor.seed_thor(csv_path=empty, db_path=db, datum_transform=IDENTITY)
    assert all(z["strike_density"] is None for z in read_zones(db).values())


def test_each_missing_required_column_fails_before_write(tmp_path):
    db = make_db(tmp_path)
    for col in thor.REQUIRED_COLUMNS:
        header = ["X_" + h if h == col else h for h in CSV_HEADER]
        path = write_csv(tmp_path, [row(102.5, 17.5)], header=header,
                         name=f"missing_{col}.csv")
        with pytest.raises(ValueError, match="missing required columns"):
            thor.seed_thor(csv_path=path, db_path=db, datum_transform=IDENTITY)
    assert all(z["strike_density"] is None for z in read_zones(db).values())


def test_failed_write_rolls_back(tmp_path):
    # A zone deleted mid-count makes the UPDATE touch fewer rows than the
    # scope; the rowcount check must roll back, not leave densities written.
    db = make_db(tmp_path)
    deleted = []

    def deleting_transform(lon, lat):
        if not deleted:
            conn = sqlite3.connect(db)
            conn.execute("DELETE FROM zones WHERE id = 'KHM.1_1'")
            conn.commit()
            conn.close()
            deleted.append(True)
        return (lon, lat)

    with pytest.raises(ValueError, match="UPDATE touched 3 rows, expected 4"):
        thor.seed_thor(csv_path=write_csv(tmp_path, [row(102.5, 17.5)]),
                       db_path=db, datum_transform=deleting_transform)
    zones = read_zones(db)
    assert "KHM.1_1" not in zones
    assert all(z["strike_density"] is None for z in zones.values())


def test_check_baseline_a_exact_and_mismatch():
    zones = [{"id": "K1", "country": "cambodia"},
             {"id": "L1", "country": "laos"},
             {"id": "V1", "country": "vietnam"}]
    counters = {
        "rows_read": 4_670_422, "baseline_assigned": 3_419_286,
        "baseline_outside": 120_990, "invalid_coords": 1_130_146,
        "baseline_mismatch": 144_697,
        "baseline_missions": {"K1": 194_836, "L1": 1_094_447, "V1": 2_130_003},
    }
    thor._check_baseline_a(counters, zones)  # exact: no raise
    thor._check_canonical_file_totals(counters)
    with pytest.raises(ValueError, match="baseline A does not reproduce"):
        thor._check_baseline_a({**counters, "rows_read": 4_670_421}, zones)
    with pytest.raises(ValueError, match="canonical CSV file totals"):
        thor._check_canonical_file_totals({**counters, "invalid_coords": 0})


def test_profile_dataset_missing_is_value_error():
    with pytest.raises(ValueError, match="strike_source.dataset"):
        thor._profile_dataset({"id": "x", "strike_source": {}})
    with pytest.raises(ValueError, match="strike_source.dataset"):
        thor._profile_dataset({"id": "x"})


def test_dedup_march_boundary_and_whitespace(tmp_path):
    rows = [
        row(102.5, 17.5, source="SACCOACT", date="19710301"),   # kept; march+
        row(102.5, 17.5, source="SACCOACT", date="19710228"),   # kept; pre-march
        row(102.5, 17.5, source=" SACCOACT ", date="19710401"),  # stripped: dropped
        row(102.5, 17.5, source="SACCOACT", date=" 19710401 "),  # stripped: dropped
    ]
    db, r = run(tmp_path, rows)
    assert r["deduped_saccoact"] == 2
    assert r["deduped_saccoact_march_variant"] == 3  # all but the 19710228 row
    assert r["assigned"] == 2 and r["missions"]["LAO.1_1"] == 2
    assert_identity(r)


def test_main_unseeded_db_returns_1(tmp_path, capsys):
    unseeded = tmp_path / "unseeded.db"
    sqlite3.connect(unseeded).close()  # file exists, no zones table
    csv_path = write_csv(tmp_path, [row(102.5, 17.5)])
    assert thor.main(["--csv", str(csv_path), "--db", str(unseeded)]) == 1
    assert "no such table" in capsys.readouterr().err


def test_main_country_dry_run_and_real_run_succeed(tmp_path):
    # CLI end-to-end with the DEFAULT (real EPSG:1542) transform; the
    # ~0.004 deg shift keeps 102.5,17.5 inside LAO.1_1.
    db = make_db(tmp_path)
    csv_path = write_csv(tmp_path, [row(102.5, 17.5)])
    assert thor.main(["--csv", str(csv_path), "--db", str(db),
                      "--country", "laos", "--dry-run"]) == 0
    assert read_zones(db)["LAO.1_1"]["strike_density"] is None
    assert thor.main(["--csv", str(csv_path), "--db", str(db),
                      "--country", "laos"]) == 0
    zones = read_zones(db)
    assert zones["LAO.1_1"]["strike_density"] > 0
    assert zones["VNM.1_1"]["strike_density"] is None


def test_default_transform_moves_point_west_northwest(tmp_path):
    # End-to-end with the real forced EPSG:1542 transform (no injection):
    # a raw point just east of the shared VNM edge shifts ~0.004 deg west.
    db = make_db(tmp_path)
    rows = [row(107.001, 16.5, tgt="SOUTH VIETNAM")]
    r = thor.seed_thor(csv_path=write_csv(tmp_path, rows), db_path=db)
    assert r["missions"]["VNM.1_1"] == 1       # shifted west across the edge
    assert r["baseline_missions"]["VNM.2_1"] == 1  # raw point was east of it
    assert_identity(r)
