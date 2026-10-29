import sqlite3, hashlib, shutil, datetime
from pathlib import Path
from backend.app.config import LOCAL_DB_PATH
print("disk free GB", shutil.disk_usage(str(LOCAL_DB_PATH.parent)).free/1e9)
src = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True)
ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
dest = Path(str(LOCAL_DB_PATH) + f".bak-stageB-{ts}")
assert not dest.exists(), dest
dst = sqlite3.connect(str(dest))
src.backup(dst)
dst.close()
chk = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
print("backup", dest, dest.stat().st_size)
print("integrity", chk.execute("PRAGMA integrity_check").fetchone())
print("counts", chk.execute("SELECT country, COUNT(*), SUM(exposure IS NOT NULL), SUM(priority_rank IS NOT NULL) FROM zones GROUP BY country ORDER BY country").fetchall())
h=hashlib.md5(dest.read_bytes()).hexdigest()
print("md5", h)
print("src_size", LOCAL_DB_PATH.stat().st_size)
chk.close(); src.close()
