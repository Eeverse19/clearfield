"""Local SQLite accessor shared by the API and the scoring runner.

One place resolves the DB path (backend.app.config.LOCAL_DB_PATH) so tests
can pass a tmp_path DB to every handler/runner without monkeypatching globals.
Raises FileNotFoundError when the file is absent; callers map that to their
own honest failure (API: 503; CLI: error exit).
"""

import sqlite3
from pathlib import Path

from backend.app.config import LOCAL_DB_PATH


def get_conn(db_path=None, *, readonly: bool = False) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else LOCAL_DB_PATH
    if not path.exists():
        raise FileNotFoundError(f"local DB not found: {path}")
    if readonly:
        # Path.resolve() can yield a \\?\ long-path prefix on Windows, which
        # is not a valid SQLite URI authority; strip it before as_uri().
        clean = Path(path.as_posix().removeprefix("//?/"))
        conn = sqlite3.connect(f"{clean.as_uri()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
