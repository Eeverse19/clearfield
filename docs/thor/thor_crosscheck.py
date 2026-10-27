import json, sqlite3, collections, pathlib
scan = json.loads(pathlib.Path(".uv-tmp/thor_scan.json").read_text(encoding="utf-8"))
pz = scan["zones"]["per_zone"]
by_country = collections.Counter(); cnt = collections.Counter()
for z in pz:
    by_country[z["country"]] += z["missions"]; cnt[z["country"]] += 1
print("per_zone_count", len(pz), dict(cnt))
print("per_zone_missions_by_zone_country", dict(by_country), "sum", sum(by_country.values()))
print("assigned_valid", scan["zones"]["assigned_valid_missions"], "unassigned", scan["zones"]["unassigned_valid_missions"])
tot_valid = sum(v["valid_coords"] for v in scan["per_tgtcountry"].values())
tot_rows = sum(v["total"] for v in scan["per_tgtcountry"].values())
tot_invalid = sum(v["invalid_coords"] for v in scan["per_tgtcountry"].values())
print("valid_sum", tot_valid, "rows_sum", tot_rows, "invalid_sum", tot_invalid, "total_rows", scan["total_rows"], "valid+invalid==rows", tot_valid+tot_invalid==tot_rows==scan["total_rows"])
print("assigned+unassigned==valid", scan["zones"]["assigned_valid_missions"]+scan["zones"]["unassigned_valid_missions"]==tot_valid)
print("per_zone_sum==assigned", sum(by_country.values())==scan["zones"]["assigned_valid_missions"])
for k,v in scan["per_tgtcountry"].items():
    ok = v["assigned"]+v["unassigned"]==v["valid_coords"] and v["valid_coords"]+v["invalid_coords"]==v["total"]
    print("tgt", k, ok, v["valid_coords"], v["assigned"], v["unassigned"])
print("mismatch_pairs_sum", sum(scan["zones"]["country_mismatch_by_pair"].values()), "total", scan["zones"]["country_mismatch_total"])
# zone-country assigned derived from tgt assigned +/- mismatches + other_implied: just print both views
la = scan["per_tgtcountry"]["LAOS"]["valid_coords"]; kh = scan["per_tgtcountry"]["CAMBODIA"]["valid_coords"]
vn = scan["per_tgtcountry"]["SOUTH VIETNAM"]["valid_coords"]+scan["per_tgtcountry"]["NORTH VIETNAM"]["valid_coords"]
print("valid_by_profile_tgt LA/KH/VN", la, kh, vn)
for name, m in scan["manifest_comparison"].items():
    print("manifest", name, m)
conn = sqlite3.connect("file:data/clearfield.db?mode=ro", uri=True)
print("zones_db", conn.execute("SELECT COUNT(*) FROM zones").fetchone())
print("strike_density_nonnull", conn.execute("SELECT COUNT(*) FROM zones WHERE strike_density IS NOT NULL").fetchone())
print("kh_crater", conn.execute("SELECT id, admin_name, crater_evidence FROM zones WHERE country='cambodia' AND crater_evidence IS NOT NULL ORDER BY crater_evidence DESC").fetchall())
print("kh_all_crater_null_count", conn.execute("SELECT COUNT(*) FROM zones WHERE country='cambodia' AND crater_evidence IS NULL").fetchone())
for zid in ("KHM.20_1","KHM.22_1","KHM.25_1"):
    print(zid, conn.execute("SELECT id,admin_name,crater_evidence,exposure,strike_density FROM zones WHERE id=?", (zid,)).fetchone(),
          [z for z in pz if z["id"]==zid])
print("top_laos", scan["top5_by_profile_country"]["laos"][0])
seed = pathlib.Path(".uv-tmp/thor_seed_spec.md").read_text(encoding="utf-8")
print("seed_spec_chars", len(seed), "lines", seed.count(chr(10))+1)
print(seed[7000:])
