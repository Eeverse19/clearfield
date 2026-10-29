-- Local-DB mirror of schema.sql for the scaffold (SQLite, no PostGIS needed).
-- Geometry is stored as GeoJSON TEXT (EPSG:4326) and is not spatially indexed.
-- Table/column names must stay identical to schema.sql so the PostGIS swap
-- changes only the connection and the geometry handling, never the scoring.

CREATE TABLE IF NOT EXISTS zones (
    id              TEXT PRIMARY KEY,
    country         TEXT NOT NULL,
    admin_name      TEXT,
    geom            TEXT,  -- GeoJSON MultiPolygon
    strike_density  REAL,
    crater_evidence REAL,
    exposure        REAL,
    building_density REAL,  -- auxiliary (pipelines/building_exposure.py); not a scoring component yet
    surveyed_status TEXT NOT NULL DEFAULT 'unsurveyed'
                    CHECK (surveyed_status IN ('unsurveyed', 'surveyed', 'cleared')),
    priority_score  REAL,
    priority_rank   INTEGER,
    scored_at       TEXT
);

CREATE TABLE IF NOT EXISTS craters (
    id          TEXT PRIMARY KEY,
    country     TEXT NOT NULL,
    source      TEXT NOT NULL,
    geom        TEXT,  -- GeoJSON Polygon
    centroid    TEXT,  -- GeoJSON Point
    area_m2     REAL,
    circularity REAL,
    confidence  REAL,
    tile_id     TEXT,
    crater_class INTEGER  -- Barthelme class 1-5; see db/schema.sql
);

CREATE TABLE IF NOT EXISTS finds (
    id            TEXT PRIMARY KEY,
    country       TEXT NOT NULL,
    zone_id       TEXT REFERENCES zones(id),
    object_type   TEXT,
    condition     TEXT,
    estimated_size TEXT,
    risk_flag     TEXT NOT NULL DEFAULT 'unknown'
                  CHECK (risk_flag IN ('unknown', 'suspect_live', 'inert', 'escalated')),
    location      TEXT,  -- GeoJSON Point
    notes         TEXT,
    photo_ref     TEXT,
    recorded_at   TEXT,
    synced_at     TEXT
);

CREATE INDEX IF NOT EXISTS zones_country_rank ON zones (country, priority_rank);
