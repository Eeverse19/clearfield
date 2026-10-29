import hashlib, sys
from pipelines.building_exposure import load_links, parse_size, LOCATIONS, BUILDINGS_DIR
rows = load_links()
p = BUILDINGS_DIR / "dataset-links.csv"
data = p.read_bytes()
print(f"links rows={len(rows)} bytes={len(data)} md5={hashlib.md5(data).hexdigest()}")
print("columns", list(rows[0].keys()) if rows else [])
grand = 0.0
for cid in ["laos", "cambodia", "vietnam"]:
    loc = LOCATIONS[cid]
    rs = [r for r in rows if r["Location"] == loc]
    total = sum(parse_size(r["Size"]) for r in rs)
    grand += total
    print(f"{cid} Location={loc} shards={len(rs)} listed_total_bytes={total:.0f} listed_GB={total/1e9:.4f} sizes={[r['Size'] for r in rs]}")
print(f"TOTAL_3COUNTRY listed_bytes={grand:.0f} GB={grand/1e9:.4f} gate1.5GB_total={'PASS' if grand <= 1.5e9 else 'FAIL'}")
for cid in ["laos", "cambodia", "vietnam"]:
    loc = LOCATIONS[cid]
    rs = [r for r in rows if r["Location"] == loc]
    total = sum(parse_size(r["Size"]) for r in rs)
    print(f"per-country gate {cid}: {'PASS' if total <= 1.5e9 else 'FAIL'} {total/1e9:.4f} GB")
