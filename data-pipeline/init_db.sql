-- =============================================================================
-- Turin Spatial Routing - PostGIS Core Schema Definition
-- =============================================================================
-- Data is managed in `data/landmarks.json` (Single Source of Truth)
-- and loaded into PostGIS via `python data-pipeline/load_to_postgis.py`.
-- =============================================================================

-- 1. Enable PostGIS Extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. Cultural Monuments & Landmarks (Supports 2D & 2.5D Viewshed Analysis)
CREATE TABLE IF NOT EXISTS monuments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    category VARCHAR(100),
    size_category VARCHAR(50),
    base_score NUMERIC(3, 1),
    height NUMERIC(5, 1), -- Landmark height in meters for 2.5D viewshed / isovists
    geometry GEOMETRY(Point, 4326)
);

-- Spatial index for accelerated distance calculations and spatial joins
CREATE INDEX IF NOT EXISTS monuments_geom_idx ON monuments USING GIST (geometry);

-- 3. Featured Historic Walking Streets
CREATE TABLE IF NOT EXISTS featured_streets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    score NUMERIC(3, 1)
);

-- 4. Featured Cultural Piazzas & Squares
CREATE TABLE IF NOT EXISTS featured_piazzas (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE
);
