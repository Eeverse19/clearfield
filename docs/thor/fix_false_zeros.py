"""One-off correction (2026-10-26): zones stored crater_evidence=0.0 by the
convex-hull coverage rule (seed defect S2 in WORKFLOW_SYNTHESIS.md) violate
the NULL != 0 invariant. For each such zone, count crater centroids actually
inside it from the seeded craters table; only if the count is 0 may the value
become NULL (meaning: coverage unknown, not imaged-and-empty)."""
import json
import sqlite3

from shapely import STRtree
from shapely.geometry import shape

conn = sqlite3.connect("data/clearfield.db")
conn.execute("PRAGMA foreign_keys=ON")
zero_zones = conn.execute(
    "SELECT id, geom FROM zones WHERE crater_evidence = 0.0").fetchall()
print("zero zones:", [z[0] for z in zero_zones])
geoms = [shape(json.loads(g)) for _, g in zero_zones]
tree = STRtree(geoms)
counts = [0] * len(geoms)
for (centroid,) in conn.execute("SELECT centroid FROM craters"):
    pt = shape(json.loads(centroid))
    for j in tree.query(pt, predicate="within"):
        counts[j] += 1
for (zone_id, _), n in zip(zero_zones, counts):
    print(zone_id, "actual crater centroids inside:", n)
    assert n == 0, f"{zone_id} has {n} craters; 0.0 was not a false zero, aborting"
conn.execute("UPDATE zones SET crater_evidence = NULL WHERE crater_evidence = 0.0")
conn.commit()
print("updated rows:", conn.execute("SELECT changes()").fetchone())
print("remaining covered:", conn.execute(
    "SELECT COUNT(*) FROM zones WHERE crater_evidence IS NOT NULL").fetchone())
