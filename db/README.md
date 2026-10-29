# db/ — schemas

- `schema.local.sql` — SQLite mirror, what runs today
  (`data/clearfield.db` via `scripts/seed_db.py`).
- `schema.sql` — PostgreSQL 15+ / PostGIS target.

Table and column names are identical between the two by design: zones
carry score *components* as columns (never only a final score), and
the explanation layer cites them. Changing one file without the other
breaks the invariant — `tests/test_local_schema.py` guards the local
side.
