"""Seed demo/cached-responses/explain-<ZONE>-en.json from stored scores.

Deterministic, key-free, no live model: reads every ranked zone from the
local DB (read-only) and writes the frozen template payload built by
backend.app.main.build_cached_explanation. Rerun after every
pipelines/scoring.py run — /explain treats files whose score_components
no longer match the DB as cache misses (501), never as stale facts.

Refuses (exit 1, writes nothing) if a ranked zone has a NULL component:
scoring never ranks such a zone, so that state means the DB is corrupt
or was hand-edited.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import config  # noqa: E402
from backend.app.db import get_conn  # noqa: E402
from backend.app.main import build_cached_explanation  # noqa: E402

COLUMNS = ("id, country, admin_name, strike_density, crater_evidence, "
           "exposure, surveyed_status, priority_score, priority_rank, "
           "scored_at")
COMPONENTS = ("strike_density", "crater_evidence", "exposure")


def main(db_path=None, out_dir=None) -> int:
    out = Path(out_dir) if out_dir is not None else config.CACHED_RESPONSES_DIR
    conn = get_conn(db_path, readonly=True)
    try:
        rows = [dict(r) for r in conn.execute(
            f"SELECT {COLUMNS} FROM zones WHERE priority_rank IS NOT NULL"
            " ORDER BY country, priority_rank")]
    finally:
        conn.close()
    bad = [r["id"] for r in rows if any(r[c] is None for c in COMPONENTS)]
    if bad:
        print(f"[cached-explanations] refusing to seed ranked zones with "
              f"NULL components: {bad}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    for row in rows:
        payload = build_cached_explanation(row, lang="en")
        path = out / f"explain-{row['id']}-en.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print(f"[cached-explanations] wrote {path.name} "
              f"({row['country']} rank {row['priority_rank']})")
    print(f"[cached-explanations] {len(rows)} file(s) in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
