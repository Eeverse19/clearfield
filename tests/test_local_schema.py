import sqlite3
from pathlib import Path

import pytest

SCHEMA = Path(__file__).resolve().parents[1] / "db" / "schema.local.sql"


def make_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "test.db")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return conn


def test_tables_and_component_columns(tmp_path):
    conn = make_db(tmp_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(zones)")}
    # Score components are stored, never just a final score (docs invariant).
    assert {"strike_density", "crater_evidence", "exposure", "surveyed_status",
            "priority_score", "priority_rank"} <= cols
    for table in ("craters", "finds"):
        assert conn.execute(f"PRAGMA table_info({table})").fetchall()


def test_surveyed_status_constraint(tmp_path):
    conn = make_db(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO zones (id, country, surveyed_status) VALUES ('z1', 'laos', 'bogus')"
        )
