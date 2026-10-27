"""THOR full streaming scan + GADM zone aggregation. Writes .uv-tmp/thor_scan.json."""
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = Path.home() / "Downloads" / "THOR_Vietnam.zip"
CSV_PATH = ROOT / "data" / "thor" / "THOR_Vietnam_7_31_2013.csv"
DB_PATH = ROOT / "data" / "clearfield.db"
OUT_PATH = ROOT / ".uv-tmp" / "thor_scan.json"

MANIFEST = {
    "LAOS": 1041519,
    "SOUTH VIETNAM": 1620422,
    "NORTH VIETNAM": 581897,
    "CAMBODIA": 144944,
    "THAILAND": 2427,
}
IMPLIED = {
    "LAOS": "laos",
    "CAMBODIA": "cambodia",
    "SOUTH VIETNAM": "vietnam",
    "NORTH VIETNAM": "vietnam",
}

t0 = time.time()


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


print("md5 zip...", flush=True)
zip_md5 = md5_of(ZIP_PATH)
print(f"zip md5={zip_md5} ({time.time()-t0:.0f}s)", flush=True)
print("md5 csv...", flush=True)
csv_md5 = md5_of(CSV_PATH)
print(f"csv md5={csv_md5} ({time.time()-t0:.0f}s)", flush=True)

# --- zones (read-only) ---
import shapely
from pyproj import Geod
from shapely import STRtree
from shapely.geometry import Point, shape

GEOD = Geod(ellps="WGS84")

conn = sqlite3.connect("file:data/clearfield.db?mode=ro", uri=True)
cols = [r[1] for r in conn.execute("PRAGMA table_info(zones)")]
print("zones cols:", cols, flush=True)
name_col = "admin_name" if "admin_name" in cols else ("name" if "name" in cols else None)
sel = "id, country, geom" + (f", {name_col}" if name_col else "")
rows = conn.execute(f"SELECT {sel} FROM zones").fetchall()
conn.close()

zones = []
for r in rows:
    geom = shapely.make_valid(shape(json.loads(r[2])))
    area_km2 = abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6
    zones.append({
        "id": r[0],
        "country": r[1],
        "admin_name": r[3] if name_col else None,
        "geom": geom,
        "area_km2": area_km2,
        "missions": 0,
        "weapons": 0,
    })
tree = STRtree([z["geom"] for z in zones])
print(f"zones loaded: {len(zones)} ({time.time()-t0:.0f}s)", flush=True)

# --- CSV scan ---
per_country = defaultdict(lambda: {
    "total": 0, "valid_coords": 0, "zero_zero": 0,
    "invalid_coords": 0, "weapons_sum_max0": 0,
    "weapons_unparseable": 0, "assigned": 0, "unassigned": 0,
})
total_rows = 0
date_min = date_max = None
date_invalid = 0
unassigned_total = 0
mismatch_total = 0
mismatch_by = defaultdict(int)  # "IMPLIED->zone_country (TGT)" -> n
other_implied_assigned = 0
other_implied_valid = 0

csv.field_size_limit(2**31 - 1)
with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    header = next(reader)
    idx = {name: i for i, name in enumerate(header)}
    print(f"header n={len(header)}", flush=True)
    for need in ("TgtCountry", "TgtLatDD_DDD_WGS84", "TgtLonDDD_DDD_WGS84",
                 "MSNDate", "NumWeaponsDelivered"):
        assert need in idx, f"missing col {need}; header={header}"
    i_cty = idx["TgtCountry"]
    i_lat = idx["TgtLatDD_DDD_WGS84"]
    i_lon = idx["TgtLonDDD_DDD_WGS84"]
    i_date = idx["MSNDate"]
    i_wep = idx["NumWeaponsDelivered"]
    ncols = len(header)
    short_rows = 0

    for row in reader:
        total_rows += 1
        if len(row) < ncols:
            short_rows += 1
            row = row + [""] * (ncols - len(row))
        cty = (row[i_cty] or "").strip().upper() or "(EMPTY)"
        pc = per_country[cty]
        pc["total"] += 1

        d = (row[i_date] or "").strip()
        if len(d) == 8 and d.isdigit():
            if date_min is None or d < date_min:
                date_min = d
            if date_max is None or d > date_max:
                date_max = d
        else:
            date_invalid += 1

        w_raw = (row[i_wep] or "").strip()
        try:
            w = int(w_raw)
        except ValueError:
            try:
                w = int(float(w_raw))
            except ValueError:
                w = 0
                pc["weapons_unparseable"] += 1
        w0 = w if w > 0 else 0
        pc["weapons_sum_max0"] += w0

        lat_s = (row[i_lat] or "").strip()
        lon_s = (row[i_lon] or "").strip()
        valid = False
        if lat_s and lon_s and lat_s.upper() != "NULL" and lon_s.upper() != "NULL":
            try:
                lat = float(lat_s)
                lon = float(lon_s)
                if lat == 0.0 and lon == 0.0:
                    pc["zero_zero"] += 1
                elif -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    valid = True
            except ValueError:
                pass
        if not valid:
            if not (lat_s and lon_s):
                pass
            pc["invalid_coords"] += 1
            continue
        pc["valid_coords"] += 1

        pt = Point(lon, lat)
        cand = tree.query(pt)
        zid = None
        for ci in cand:
            if zones[int(ci)]["geom"].covers(pt):
                zid = int(ci)
                break
        implied = IMPLIED.get(cty)
        if zid is None:
            pc["unassigned"] += 1
            unassigned_total += 1
            if implied is None:
                other_implied_valid += 1
        else:
            pc["assigned"] += 1
            z = zones[zid]
            z["missions"] += 1
            z["weapons"] += w0
            if implied is None:
                other_implied_valid += 1
                other_implied_assigned += 1
            elif implied != z["country"]:
                mismatch_total += 1
                mismatch_by[f"{cty} (implied {implied}) -> zone {z['country']}"] += 1
        if total_rows % 1000000 == 0:
            print(f"rows={total_rows} ({time.time()-t0:.0f}s)", flush=True)

print(f"scan done rows={total_rows} ({time.time()-t0:.0f}s)", flush=True)

# note: invalid_coords above counts zero_zero rows too; split for clarity
per_country_out = {}
for cty, pc in sorted(per_country.items()):
    d = dict(pc)
    d["invalid_coords_excl_zero_zero"] = pc["invalid_coords"] - pc["zero_zero"]
    per_country_out[cty] = d

manifest_cmp = {}
for cty, claim in MANIFEST.items():
    got = per_country_out.get(cty, {}).get("valid_coords", 0)
    manifest_cmp[cty] = {
        "manifest_with_coords": claim,
        "actual_valid_coords": got,
        "diff_actual_minus_manifest": got - claim,
        "match": got == claim,
    }

zone_rows = []
for z in zones:
    dens = z["missions"] / z["area_km2"] if z["area_km2"] > 0 else None
    zone_rows.append({
        "id": z["id"], "country": z["country"], "admin_name": z["admin_name"],
        "area_km2": round(z["area_km2"], 3), "missions": z["missions"],
        "weapons": z["weapons"],
        "missions_per_km2": round(dens, 6) if dens is not None else None,
    })
zone_rows.sort(key=lambda r: (r["country"], -(r["missions_per_km2"] or 0)))

top5 = {}
for prof in ("laos", "cambodia", "vietnam"):
    zr = sorted((r for r in zone_rows if r["country"] == prof),
                key=lambda r: -(r["missions_per_km2"] or 0))[:5]
    top5[prof] = zr

disk = shutil.disk_usage(str(ROOT))
out = {
    "zip": {"path": str(ZIP_PATH), "size": ZIP_PATH.stat().st_size, "md5": zip_md5},
    "csv": {"path": str(CSV_PATH), "size": CSV_PATH.stat().st_size, "md5": csv_md5,
            "header_ncols": len(header), "header": header,
            "short_rows_padded": short_rows},
    "disk": {"total": disk.total, "used": disk.used, "free": disk.free,
             "free_gb": round(disk.free / 1e9, 1)},
    "total_rows": total_rows,
    "msndate": {"min": date_min, "max": date_max, "invalid_or_empty": date_invalid},
    "per_tgtcountry": per_country_out,
    "manifest_comparison": manifest_cmp,
    "manifest_all_match": all(v["match"] for v in manifest_cmp.values()),
    "zones": {"count": len(zones), "columns": cols,
              "unassigned_valid_missions": unassigned_total,
              "assigned_valid_missions": sum(z["missions"] for z in zones),
              "country_mismatch_total": mismatch_total,
              "country_mismatch_by_pair": dict(sorted(mismatch_by.items(), key=lambda kv: -kv[1])),
              "other_implied_valid": other_implied_valid,
              "other_implied_assigned": other_implied_assigned,
              "per_zone": zone_rows},
    "top5_by_profile_country": top5,
    "elapsed_s": round(time.time() - t0, 1),
}
OUT_PATH.write_text(json.dumps(out, indent=1), encoding="utf-8")
print("WROTE", OUT_PATH, OUT_PATH.stat().st_size, flush=True)
print("=== HEADLINES ===", flush=True)
print(f"rows={total_rows} dates={date_min}..{date_max} date_invalid={date_invalid}", flush=True)
for cty, d in per_country_out.items():
    print(f"{cty}: total={d['total']} valid={d['valid_coords']} zero00={d['zero_zero']} weapons={d['weapons_sum_max0']} assigned={d['assigned']} unassigned={d['unassigned']}", flush=True)
for cty, v in manifest_cmp.items():
    print(f"manifest {cty}: claim={v['manifest_with_coords']} actual={v['actual_valid_coords']} diff={v['diff_actual_minus_manifest']} match={v['match']}", flush=True)
print(f"unassigned={unassigned_total} mismatch={mismatch_total} other_implied_valid={other_implied_valid} assigned_other={other_implied_assigned}", flush=True)
for prof, zr in top5.items():
    if zr:
        top = zr[0]
        print(f"top {prof}: {top['id']} {top['admin_name']} dens={top['missions_per_km2']} missions={top['missions']} area={top['area_km2']}", flush=True)
print(f"elapsed={out['elapsed_s']}s", flush=True)
