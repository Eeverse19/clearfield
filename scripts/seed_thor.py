"""Seed zones.strike_density from the THOR Vietnam War mission archive.

See seed_thor.ps1/.sh wrappers. Spec: docs/thor/thor_final_spec.md §2 as
amended by §9 (Barthelme et al. 2024 corrections).

strike_density = THOR missions per km2 of zone area (WGS84 geodesic area).
Every valid-coordinate row is exactly 1 mission (U17); WeaponType,
NumWeaponsDelivered, NumOfAcft and Weapons*Weight are never inspected
(§9.3: the Barthelme weapon filter is a weapons-delivered metric and is NOT
applied; weapon_excluded stays 0). Two Barthelme corrections ARE applied:

- Datum (§9.1): the *_WGS84 coordinate columns are actually Indian 1960
  (EPSG:4131). Each valid point is converted EPSG:4131 -> EPSG:4326 forcing
  operation EPSG:1542 (~500 m shift) before point-in-zone assignment.
  Coordinates are stored nowhere; the datum changes assignment only.
- B-52 dedup (§9.2): valid-coord rows with SourceRecord == "SACCOACT" and
  MSNDate >= "19710401" (raw YYYYMMDD) duplicate SEADAB records; they are
  dropped and counted as deduped_saccoact, never assigned.

Zone assignment is point-in-zone ONLY. TgtCountry is a cross-check that is
counted (144,697 mismatches on the uncorrected baseline) and never filters
or reassigns a row; profiles' strike_source.country_filter lists document
the expected TgtCountry values and are likewise never used to filter.

Zero-mission zones get a real 0.0 (THOR covers all three countries, so 0 is
a measured zero — unlike crater_evidence, where NULL means "no coverage").

This script's ONLY write is UPDATE zones SET strike_density, in one
transaction, after reconciliation closes. Reconciliation mismatch, missing
CSV, or a bad header all fail (exit 1) BEFORE any write. Idempotent: the
result is a pure function of (CSV bytes, zone geoms).

The CSV is a manual download (data.world/datamil/vietnam-war-thor-data);
the zip is Deflate64, which Python zipfile and Windows tar cannot read.
Extract with 7-Zip:
& 'C:\\Program Files\\7-Zip\\7z.exe' e ~/Downloads/THOR_Vietnam.zip -odata\\thor
"""

import argparse
import csv
import json
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyproj import Geod, Transformer  # noqa: E402
from pyproj.aoi import AreaOfInterest  # noqa: E402
from shapely import STRtree  # noqa: E402
from shapely.geometry import Point, shape  # noqa: E402

from backend.app.config import LOCAL_DB_PATH, REPO_ROOT  # noqa: E402
from backend.app.db import get_conn  # noqa: E402
from backend.app.profiles import list_countries, load_country  # noqa: E402

GEOD = Geod(ellps="WGS84")

EXPECTED_CSV_BYTES = 2_627_971_171
EXTRACT_COMMAND = (
    r"& 'C:\Program Files\7-Zip\7z.exe' e ~/Downloads/THOR_Vietnam.zip -odata\thor"
)

REQUIRED_COLUMNS = (
    "SourceRecord",
    "MSNDate",
    "TgtCountry",
    "TgtLatDD_DDD_WGS84",
    "TgtLonDDD_DDD_WGS84",
)
IND60_COLUMNS = ("TgtLatDD_DDD_IND60", "TgtLonDDD_DDD_IND60")

DEDUP_SOURCE = "SACCOACT"
DEDUP_CUTOFF = "19710401"  # analysis.py rule; MSNDate is fixed-width YYYYMMDD
DEDUP_CUTOFF_MARCH_VARIANT = "19710301"  # supplement-text date (diagnostic, D3)

INVALID_REASONS = ("empty", "null_literal", "unparseable", "out_of_range", "zero_zero")

# data.world manifest claims (spec §0) — printed claim-vs-observed as WARN
# only; observed is truth, never an adjustment.
MANIFEST_CLAIMS = {
    "LAOS": 1_041_519,
    "SOUTH VIETNAM": 1_620_422,
    "NORTH VIETNAM": 581_897,
    "CAMBODIA": 144_944,
    "THAILAND": 2_427,
}

# Uncorrected baseline A (spec §2.6 numbers, demoted by §9.4). On a canonical
# all-country run these must reproduce exactly or the run fails before write.
# mismatch/missions differ from §2.6 (144,672; KH 194,809 / VN 2,130,030):
# the §0 scan took the first covers-hit in STRtree order for points exactly
# on a shared border, while §2.4 mandates smallest zones.id. 70 such border
# points change owner (net KH +27 / VN -27, mismatch +25); assigned/outside
# totals are identical. Values below are the §2.4-rule baseline, observed
# 2026-10-28.
BASELINE_A = {
    "rows_read": 4_670_422,
    "baseline_assigned": 3_419_286,
    "baseline_outside": 120_990,
    "invalid_coords": 1_130_146,
    "baseline_mismatch": 144_697,
    "baseline_missions_by_country": {
        "cambodia": 194_836,
        "laos": 1_094_447,
        "vietnam": 2_130_003,
    },
}

_TGT_COUNTRY_MAP = {
    "LAOS": "laos",
    "CAMBODIA": "cambodia",
    "SOUTH VIETNAM": "vietnam",
    "NORTH VIETNAM": "vietnam",
    "THAILAND": "thailand",
}
_PROFILE_COUNTRIES = ("laos", "cambodia", "vietnam")


def make_datum_transform():
    """EPSG:4131 (Indian 1960) -> EPSG:4326, forcing operation EPSG:1542."""
    t = Transformer.from_crs(
        "EPSG:4131", "EPSG:4326", always_xy=True,
        area_of_interest=AreaOfInterest(
            west_lon_degree=105.61, south_lat_degree=14.0,
            east_lon_degree=109.36, north_lat_degree=18.01))
    # Fail loud if PROJ ever selects the Ballpark/noop operation instead.
    for (lon, lat), (exp_lon, exp_lat) in [
            ((107.0, 16.8), (106.99580732082036, 16.801609276893966)),
            ((102.6, 17.97), (102.5963613440926, 17.97141995372316))]:  # forced
        got_lon, got_lat = t.transform(lon, lat)
        if abs(got_lon - exp_lon) > 1e-6 or abs(got_lat - exp_lat) > 1e-6:
            raise ValueError("EPSG:1542 datum transform not in effect")
    return lambda lon, lat: t.transform(lon, lat)


def parse_point(lat_raw, lon_raw):
    """Return (lon, lat) floats, or the first matching invalid reason (str).

    Reasons are checked in spec §2.3 order across both fields: empty,
    null_literal, unparseable (float raises or NaN/inf), out_of_range,
    zero_zero. Nothing is repaired.
    """
    lat_s = (lat_raw or "").strip()
    lon_s = (lon_raw or "").strip()
    if not lat_s or not lon_s:
        return "empty"
    if lat_s.upper() == "NULL" or lon_s.upper() == "NULL":
        return "null_literal"
    try:
        lat = float(lat_s)
        lon = float(lon_s)
    except ValueError:
        return "unparseable"
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return "unparseable"
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return "out_of_range"
    if lat == 0.0 and lon == 0.0:  # -0.0 == 0.0, so both signs land here
        return "zero_zero"
    return (lon, lat)


def map_tgt_country(raw) -> str:
    """Map a raw TgtCountry value to a profile id / thailand / unknown."""
    return _TGT_COUNTRY_MAP.get((raw or "").strip().upper(), "unknown")


def _profile_dataset(profile) -> str:
    """Profile strike_source.dataset, as a clean ValueError when absent."""
    source = profile.get("strike_source") if isinstance(profile, dict) else None
    dataset = source.get("dataset") if isinstance(source, dict) else None
    if not isinstance(dataset, str) or not dataset:
        raise ValueError(
            f"country profile {profile.get('id', '?') if isinstance(profile, dict) else '?'}: "
            "strike_source.dataset is missing or not a non-empty string")
    return dataset


def resolve_csv_path(csv_path=None, country=None) -> Path:
    """Resolve the THOR CSV. Default: profiles' strike_source.dataset.

    All-country runs assert every profile agrees on the dataset (spec §2.1);
    --country runs use that profile's dataset. An explicit csv_path (tests)
    skips the profile lookup entirely.
    """
    if csv_path is not None:
        path = Path(csv_path)
        return path if path.is_absolute() else REPO_ROOT / path
    if country is not None:
        datasets = {_profile_dataset(load_country(country))}
    else:
        datasets = {_profile_dataset(p) for p in list_countries()}
    if len(datasets) != 1:
        raise ValueError(f"country profiles disagree on THOR dataset: {sorted(datasets)}")
    return REPO_ROOT / datasets.pop()


def missing_csv_message(path) -> str:
    return (
        f"THOR CSV not found: {path}\n"
        "THOR is a manual download (data.world/datamil/vietnam-war-thor-data); "
        "the zip is Deflate64, which Python zipfile and Windows tar cannot "
        "read. Extract it with 7-Zip:\n"
        f"{EXTRACT_COMMAND}"
    )


def load_zones(conn, country=None) -> list[dict]:
    """Load zones in scope from the DB; fail loudly on any unusable geom."""
    if country is not None:
        rows = conn.execute(
            "SELECT id, country, geom FROM zones WHERE country = ? ORDER BY id",
            (country,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, country, geom FROM zones ORDER BY id").fetchall()
    if not rows:
        scope = f"country {country!r}" if country else "any country"
        raise ValueError(f"no zones in DB for {scope}; run scripts/seed_db.py first")
    zones = []
    for row in rows:
        zid, zcountry, geom_text = row["id"], row["country"], row["geom"]
        if geom_text is None:
            raise ValueError(f"zone {zid}: geom is NULL")
        try:
            geom = shape(json.loads(geom_text))
        except Exception as exc:
            raise ValueError(f"zone {zid}: unparseable geom: {exc}") from exc
        if geom.is_empty or not geom.is_valid:
            raise ValueError(f"zone {zid}: geom is empty or invalid")
        area_km2 = abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6
        if not math.isfinite(area_km2) or area_km2 <= 0:
            raise ValueError(f"zone {zid}: geodesic area_km2 {area_km2!r} <= 0")
        zones.append({"id": zid, "country": zcountry, "geom": geom,
                      "area_km2": area_km2})
    return zones


def _assign(tree, zones, lon, lat):
    """Point-in-zone: (zone_dict_or_None, n_hits). >1 hit -> smallest id.

    Spec §2.4 says predicate="covers" (zone covers point, boundary
    included), but shapely 2.2 evaluates STRtree predicates as
    predicate(input, tree_geometry) — so zone-covers-point is spelled
    "covered_by" here (point covered_by zone). Verified empirically:
    "covers" matches nothing, "within" drops boundary points,
    "covered_by" keeps them (cf. pipelines/osm_exposure.py:349-352).
    """
    hits = [int(i) for i in tree.query(Point(lon, lat), predicate="covered_by")]
    if not hits:
        return None, 0
    if len(hits) > 1:
        hits.sort(key=lambda i: zones[i]["id"])
    return zones[hits[0]], len(hits)


def count_missions(csv_path, zones, datum_transform, scoped: bool) -> dict:
    """One streaming pass over the CSV. Pure counting; writes nothing.

    Gate order per row (§9.4): coord validity -> dedup -> weapon gate
    (never excludes, §9.3) -> datum transform -> point-in-zone. The same
    pass also tallies baseline A (raw point, no dedup) and datum-only B
    (transformed point, no dedup) so every delta vs §2.6 is explained.
    """
    tree = STRtree([z["geom"] for z in zones])
    missions = {z["id"]: 0 for z in zones}           # C: corrected, written
    baseline_missions = {z["id"]: 0 for z in zones}  # A: report only
    invalid_reasons = Counter()
    matrix = Counter()           # C mismatches: "TGT->zone_country"
    tgt_valid = Counter()        # valid-coord rows per raw TgtCountry value
    examples = []
    c = {
        "rows_read": 0, "assigned": 0, "invalid_coords": 0,
        "outside_zones": 0, "outside_scope": 0, "multi_hit": 0,
        "mismatch": 0, "deduped_saccoact": 0, "weapon_excluded": 0,
        "baseline_assigned": 0, "baseline_outside": 0, "baseline_mismatch": 0,
        "datum_assigned": 0, "datum_outside": 0,
        "deduped_saccoact_march_variant": 0, "ind60_ne_wgs84": 0,
    }
    # csv.field_size_limit(sys.maxsize) overflows C long on Windows.
    limit = sys.maxsize
    while limit > 0:
        try:
            csv.field_size_limit(limit)
            break
        except OverflowError:
            limit //= 10
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{csv_path}: empty file, no header row")
        idx = {name: i for i, name in enumerate(header)}
        missing = [name for name in REQUIRED_COLUMNS if name not in idx]
        if missing:
            raise ValueError(f"{csv_path}: missing required columns {missing}")
        have_ind60 = all(name in idx for name in IND60_COLUMNS)
        ncols = len(header)
        i_src, i_date, i_tgt = idx["SourceRecord"], idx["MSNDate"], idx["TgtCountry"]
        i_lat, i_lon = (
            idx["TgtLatDD_DDD_WGS84"], idx["TgtLonDDD_DDD_WGS84"])
        for row_no, row in enumerate(reader, start=1):
            c["rows_read"] += 1
            if c["rows_read"] % 500_000 == 0:
                print(f"  ... {c['rows_read']:,} rows", flush=True)
            if len(row) < ncols:  # scanner behaviour (§0): pad short rows
                row = row + [""] * (ncols - len(row))
            point = parse_point(row[i_lat], row[i_lon])
            if isinstance(point, str):
                c["invalid_coords"] += 1
                invalid_reasons[point] += 1
                continue
            lon, lat = point
            tgt_raw = row[i_tgt]
            tgt_valid[tgt_raw.strip().upper() or "(EMPTY)"] += 1
            if have_ind60 and (
                    row[idx[IND60_COLUMNS[0]]].strip() != row[i_lat].strip()
                    or row[idx[IND60_COLUMNS[1]]].strip() != row[i_lon].strip()):
                c["ind60_ne_wgs84"] += 1
            # A — uncorrected baseline: raw point, no dedup, no weapon gate.
            base_zone, _ = _assign(tree, zones, lon, lat)
            mapped = map_tgt_country(tgt_raw)
            if base_zone is None:
                c["baseline_outside"] += 1
            else:
                c["baseline_assigned"] += 1
                baseline_missions[base_zone["id"]] += 1
                if mapped in _PROFILE_COUNTRIES and mapped != base_zone["country"]:
                    c["baseline_mismatch"] += 1
            # Dedup gate (valid-coord rows only). Raw YYYYMMDD string compare.
            is_saccoact = row[i_src].strip() == DEDUP_SOURCE
            msndate = row[i_date].strip()
            if is_saccoact and msndate >= DEDUP_CUTOFF_MARCH_VARIANT:
                c["deduped_saccoact_march_variant"] += 1
            deduped = is_saccoact and msndate >= DEDUP_CUTOFF
            # Weapon gate: never excludes (§9.3, U17); weapon_excluded stays 0.
            # §9.1 "dropped rows are never transformed" conflicts with §9.4,
            # which defines B (dedup not applied) and the dedup delta via
            # deduped rows' transformed points. Deduped rows are therefore
            # transformed ONLY for the B tally below, never for the C counts
            # that are written (the `continue` at the C gate).
            t_lon, t_lat = datum_transform(lon, lat)
            # B — datum-only: transformed point, dedup not applied.
            datum_zone, datum_hits = _assign(tree, zones, t_lon, t_lat)
            if datum_zone is None:
                c["datum_outside"] += 1
            else:
                c["datum_assigned"] += 1
            # C — corrected: the only counts written.
            if deduped:
                c["deduped_saccoact"] += 1
                continue
            if datum_zone is None:
                c["outside_scope" if scoped else "outside_zones"] += 1
                continue
            if datum_hits > 1:
                c["multi_hit"] += 1
            missions[datum_zone["id"]] += 1
            c["assigned"] += 1
            if mapped in _PROFILE_COUNTRIES and mapped != datum_zone["country"]:
                c["mismatch"] += 1
                matrix[f"{tgt_raw.strip().upper()}->{datum_zone['country']}"] += 1
                if len(examples) < 10:
                    # Raw CSV coordinates, so an owner can spot-check the row
                    # against the source file (not the datum-shifted point).
                    examples.append((row_no, tgt_raw.strip(),
                                     datum_zone["id"], lat, lon))
    c["invalid_reasons"] = {r: invalid_reasons.get(r, 0) for r in INVALID_REASONS}
    c["missions"] = missions
    c["baseline_missions"] = baseline_missions
    c["mismatch_matrix"] = dict(matrix)
    c["mismatch_examples"] = examples
    c["tgtcountry_valid"] = dict(tgt_valid)
    c["ind60_present"] = have_ind60
    return c


def _by_country(zones, missions):
    out = {}
    for z in zones:
        out[z["country"]] = out.get(z["country"], 0) + missions[z["id"]]
    return out


def _check_baseline_a(counters, zones):
    """Canonical all-country runs must reproduce baseline A exactly (§9.4)."""
    observed = {
        "rows_read": counters["rows_read"],
        "baseline_assigned": counters["baseline_assigned"],
        "baseline_outside": counters["baseline_outside"],
        "invalid_coords": counters["invalid_coords"],
        "baseline_mismatch": counters["baseline_mismatch"],
        "baseline_missions_by_country": _by_country(
            zones, counters["baseline_missions"]),
    }
    if observed != BASELINE_A:
        raise ValueError(
            "baseline A does not reproduce spec 2.6 (DB untouched): "
            f"observed {observed} != expected {BASELINE_A}")


def _check_canonical_file_totals(counters):
    """File-wide baseline totals for canonical --country runs (§9.4).

    rows_read and invalid_coords are tallied before any zone assignment,
    so they are scope-independent: a truncated canonical CSV fails here
    even though the assigned/mismatch A-numbers are in-scope only.
    """
    observed = {
        "rows_read": counters["rows_read"],
        "invalid_coords": counters["invalid_coords"],
    }
    expected = {
        "rows_read": BASELINE_A["rows_read"],
        "invalid_coords": BASELINE_A["invalid_coords"],
    }
    if observed != expected:
        raise ValueError(
            "canonical CSV file totals do not reproduce spec 2.6 "
            f"(DB untouched): observed {observed} != expected {expected}")


def seed_thor(csv_path=None, db_path=None, country=None, dry_run=False,
              datum_transform=None) -> dict:
    """Compute THOR strike densities and (unless dry_run) write them.

    The only write is UPDATE zones SET strike_density for zones in scope,
    in one transaction, after reconciliation closes. datum_transform=None
    builds the forced EPSG:1542 transform (§9.1); tests inject a stub.
    Returns the counters dict (tests assert on it, not on stdout).
    """
    canonical = csv_path is None  # baseline-A gate applies to canonical runs
    if country is not None:
        load_country(country)  # validate the id before touching anything
    resolved_csv = resolve_csv_path(csv_path, country)
    if not resolved_csv.exists():
        raise FileNotFoundError(missing_csv_message(resolved_csv))
    csv_bytes = resolved_csv.stat().st_size
    print(f"csv: {resolved_csv} ({csv_bytes:,} bytes)")
    if csv_bytes != EXPECTED_CSV_BYTES:
        print(f"WARN: csv size {csv_bytes:,} != expected "
              f"{EXPECTED_CSV_BYTES:,} bytes (spec section 0)")
    resolved_db = Path(db_path) if db_path is not None else LOCAL_DB_PATH
    if datum_transform is None:
        datum_transform = make_datum_transform()

    conn = get_conn(db_path)
    try:
        zones = load_zones(conn, country)
        zones_by_country = Counter(z["country"] for z in zones)
        print(f"zones in scope: {len(zones)} ({dict(sorted(zones_by_country.items()))})")
        counters = count_missions(resolved_csv, zones, datum_transform,
                                  scoped=country is not None)
        missions = counters.pop("missions")
        baseline_missions = counters.pop("baseline_missions")

        if counters["rows_read"] == 0:
            raise ValueError(
                f"{resolved_csv}: no data rows (header only?); "
                "refusing to write zero densities (DB untouched)")

        # Reconciliation closes BEFORE any write (§9.4).
        identity_rhs = (
            counters["assigned"] + counters["invalid_coords"]
            + counters["outside_zones"] + counters["outside_scope"]
            + counters["deduped_saccoact"] + counters["weapon_excluded"])
        if counters["rows_read"] != identity_rhs:
            raise ValueError(
                f"reconciliation mismatch: rows_read {counters['rows_read']} != "
                f"assigned+invalid+outside+deduped+weapon_excluded {identity_rhs} "
                "(DB untouched)")
        if counters["assigned"] != sum(missions.values()):
            raise ValueError("reconciliation mismatch: assigned != sum of zone "
                             "missions (DB untouched)")
        datum_delta = counters["datum_assigned"] - counters["baseline_assigned"]
        dedup_delta = counters["assigned"] - counters["datum_assigned"]
        if counters["assigned"] - counters["baseline_assigned"] != datum_delta + dedup_delta:
            raise ValueError("reconciliation mismatch: C-A != datum delta + "
                             "dedup delta (DB untouched)")
        counters["baseline_missions"] = baseline_missions
        if canonical and country is None:
            _check_baseline_a(counters, zones)
        elif canonical:
            _check_canonical_file_totals(counters)
        counters.pop("baseline_missions")
        counters["datum_delta"] = datum_delta
        counters["dedup_delta"] = dedup_delta
        counters["missions_by_country"] = _by_country(zones, missions)
        counters["baseline_missions_by_country"] = _by_country(
            zones, baseline_missions)

        densities = {z["id"]: missions[z["id"]] / z["area_km2"] for z in zones}
        for zid, value in densities.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"zone {zid}: strike_density {value!r} invalid")
        _print_report(counters, zones, missions, densities, dry_run)

        zones_written = 0
        integrity = fk_violations = null_remaining = None
        if not dry_run:
            rows = [(densities[z["id"]], z["id"]) for z in zones]
            # Every check runs INSIDE the transaction: a failure here rolls
            # the UPDATE back instead of leaving densities written.
            with conn:
                cur = conn.executemany(
                    "UPDATE zones SET strike_density = ? WHERE id = ?", rows)
                if cur.rowcount != len(zones):
                    raise ValueError(
                        f"UPDATE touched {cur.rowcount} rows, "
                        f"expected {len(zones)}")
                zones_written = cur.rowcount
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                fk_violations = len(
                    conn.execute("PRAGMA foreign_key_check").fetchall())
                if country is not None:
                    null_remaining = conn.execute(
                        "SELECT COUNT(*) FROM zones WHERE strike_density IS NULL "
                        "AND country = ?", (country,)).fetchone()[0]
                else:
                    null_remaining = conn.execute(
                        "SELECT COUNT(*) FROM zones WHERE strike_density IS NULL"
                    ).fetchone()[0]
                if integrity != "ok" or fk_violations or null_remaining:
                    raise ValueError(
                        f"post-write check failed: integrity {integrity!r}, fk "
                        f"violations {fk_violations}, NULL strike_density in "
                        f"scope {null_remaining}")
        print(f"zones written: {zones_written}; NULL strike_density in scope: "
              f"{null_remaining}; integrity {integrity}; fk violations "
              f"{fk_violations}")
        print(f"db: {resolved_db}")
    finally:
        conn.close()

    counters["missions"] = missions
    counters["baseline_missions"] = baseline_missions
    return {
        "csv": str(resolved_csv),
        "csv_bytes": csv_bytes,
        "db": str(resolved_db),
        "country": country,
        "dry_run": dry_run,
        "zones": len(zones),
        "zones_by_country": dict(zones_by_country),
        "densities": densities,
        "zones_written": zones_written,
        "integrity": integrity,
        "fk_violations": fk_violations,
        "null_strike_density_in_scope": null_remaining,
        **counters,
    }


def _print_report(c, zones, missions, densities, dry_run):
    print(f"rows_read: {c['rows_read']:,}")
    print(f"assigned (C corrected): {c['assigned']:,}")
    print(f"invalid_coords: {c['invalid_coords']:,} {c['invalid_reasons']}")
    print(f"outside_zones: {c['outside_zones']:,}; outside_scope: "
          f"{c['outside_scope']:,}")
    print(f"deduped_saccoact: {c['deduped_saccoact']:,} "
          f"(march variant diagnostic: {c['deduped_saccoact_march_variant']:,}); "
          f"weapon_excluded: {c['weapon_excluded']:,}")
    print(f"baseline A assigned: {c['baseline_assigned']:,} (outside "
          f"{c['baseline_outside']:,}, mismatch {c['baseline_mismatch']:,}); "
          f"datum-only B assigned: {c['datum_assigned']:,}; "
          f"datum delta B-A: {c['datum_delta']:+,}; dedup delta C-B: "
          f"{c['dedup_delta']:+,}")
    if c["ind60_present"]:
        print(f"ind60_ne_wgs84 (diagnostic, D2): {c['ind60_ne_wgs84']:,}")
    print(f"multi_hit: {c['multi_hit']:,}")
    print(f"TgtCountry mismatch (C): {c['mismatch']:,} {c['mismatch_matrix']}")
    for ex in c["mismatch_examples"]:
        print(f"  mismatch example row {ex[0]}: TgtCountry={ex[1]!r} "
              f"zone={ex[2]} lat={ex[3]} lon={ex[4]}")
    print("manifest claims vs observed valid-coord rows (WARN only):")
    for tgt, claim in MANIFEST_CLAIMS.items():
        observed = c["tgtcountry_valid"].get(tgt, 0)
        flag = "" if observed == claim else "  WARN"
        print(f"  {tgt}: claim {claim:,} observed {observed:,} "
              f"delta {observed - claim:+,}{flag}")
    for country_id in sorted({z["country"] for z in zones}):
        czones = [z for z in zones if z["country"] == country_id]
        vals = [densities[z["id"]] for z in czones]
        top5 = sorted(czones, key=lambda z: -densities[z["id"]])[:5]
        top = ", ".join(
            f"{z['id']} ({missions[z['id']]:,} missions, "
            f"{z['area_km2']:,.1f} km2, {densities[z['id']]:.6f})" for z in top5)
        print(f"{country_id}: {len(czones)} zones, "
              f"{c['missions_by_country'][country_id]:,} missions, density "
              f"min {min(vals):.6f} max {max(vals):.6f}; top-5: {top}")
    if dry_run:
        print("dry run - would write (zone_id, missions, strike_density):")
        for z in zones:
            print(f"  {z['id']} {missions[z['id']]:,} {densities[z['id']]:.6f}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed zones.strike_density from the THOR archive "
                    "(docs/thor/thor_final_spec.md sections 2/9).")
    parser.add_argument("--country", default=None,
                        help="only this country's zones (CSV still fully scanned)")
    parser.add_argument("--csv", default=None, help="THOR CSV path (tests only)")
    parser.add_argument("--db", default=None, help="SQLite DB path")
    parser.add_argument("--dry-run", action="store_true",
                        help="count and report; write nothing")
    args = parser.parse_args(argv)
    try:
        seed_thor(csv_path=args.csv, db_path=args.db, country=args.country,
                  dry_run=args.dry_run)
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
