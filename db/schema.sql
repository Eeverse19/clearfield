-- ClearField canonical schema (PostgreSQL 15+ / PostGIS target).
-- The scaffold runs on the local mirror in schema.local.sql (SQLite);
-- table and column names must stay identical between the two.
--
-- INVARIANT: zones carry score *components* as columns, never only a final
-- score. The explanation layer cites these numbers; dropping a component
-- column in a migration breaks "why is this zone ranked #3?".

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS zones (
    id              TEXT PRIMARY KEY,
    country         TEXT NOT NULL,
    admin_name      TEXT,
    geom            GEOMETRY(MultiPolygon, 4326),
    -- Score components (deterministic inputs, stored for citation).
    strike_density  DOUBLE PRECISION,
    crater_evidence DOUBLE PRECISION,
    exposure        DOUBLE PRECISION,
    -- Auxiliary settlement signal (Microsoft building footprints/km2,
    -- pipelines/building_exposure.py). Not read by scoring.py until a
    -- scoring decision blends it; stored so the choice is auditable.
    building_density DOUBLE PRECISION,
    surveyed_status TEXT NOT NULL DEFAULT 'unsurveyed'
                    CHECK (surveyed_status IN ('unsurveyed', 'surveyed', 'cleared')),
    -- Derived by pipelines/scoring.py from the components above. Nothing else
    -- may write these two columns.
    priority_score  DOUBLE PRECISION,
    priority_rank   INTEGER,
    scored_at       TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS craters (
    id          TEXT PRIMARY KEY,
    country     TEXT NOT NULL,
    source      TEXT NOT NULL,  -- e.g. 'barthelme_predictions', 'sam31'
    geom        GEOMETRY(Polygon, 4326),
    centroid    GEOMETRY(Point, 4326),
    area_m2     DOUBLE PRECISION,
    circularity DOUBLE PRECISION,
    confidence  DOUBLE PRECISION,
    tile_id     TEXT,
    -- Barthelme morphology class (1 Pattern, 2 Rim, 3 Group, 4 Crescent,
    -- 5 Bowl); NULL for sources without classes (e.g. SAM) and for rows
    -- seeded before this column existed.
    crater_class INTEGER
);

-- Field triage records (Glimmer offline) sync into this table unchanged:
-- one schema for HQ and field, by design.
CREATE TABLE IF NOT EXISTS finds (
    id            TEXT PRIMARY KEY,
    country       TEXT NOT NULL,
    zone_id       TEXT REFERENCES zones(id),
    object_type   TEXT,
    condition     TEXT,
    estimated_size TEXT,
    risk_flag     TEXT NOT NULL DEFAULT 'unknown'
                  CHECK (risk_flag IN ('unknown', 'suspect_live', 'inert', 'escalated')),
    location      GEOMETRY(Point, 4326),
    notes         TEXT,
    photo_ref     TEXT,
    recorded_at   TIMESTAMPTZ,
    synced_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS zones_country_rank ON zones (country, priority_rank);
CREATE INDEX IF NOT EXISTS zones_geom_gix ON zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS craters_geom_gix ON craters USING GIST (geom);
CREATE INDEX IF NOT EXISTS finds_location_gix ON finds USING GIST (location);
