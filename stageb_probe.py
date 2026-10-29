import sqlite3, sys, json
from backend.app.config import LOCAL_DB_PATH
print("DB", LOCAL_DB_PATH)
c = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True)
print("journal", c.execute("PRAGMA journal_mode").fetchone())
cols = [r[1] for r in c.execute("PRAGMA table_info(zones)")]
print("cols", cols)
print("has_building_density", "building_density" in cols)
print(c.execute("SELECT country, COUNT(*), SUM(exposure IS NOT NULL), SUM(priority_rank IS NOT NULL) FROM zones GROUP BY country ORDER BY country").fetchall())
if "building_density" in cols:
    print("density", c.execute("SELECT country, COUNT(*), SUM(building_density IS NOT NULL), SUM(building_density>0) FROM zones GROUP BY country ORDER BY country").fetchall())
print("ranked", c.execute("SELECT id, country, priority_score, priority_rank, scored_at FROM zones WHERE priority_rank IS NOT NULL ORDER BY country, priority_rank").fetchall())
