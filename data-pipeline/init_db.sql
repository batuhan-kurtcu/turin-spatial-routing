-- Create database and extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- Define Schema
CREATE TABLE IF NOT EXISTS monuments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    size_category VARCHAR(50),
    base_score NUMERIC(3, 1),
    location GEOMETRY(Point, 4326)
);

CREATE TABLE IF NOT EXISTS featured_streets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    score NUMERIC(3, 1)
);

CREATE TABLE IF NOT EXISTS featured_piazzas (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE
);

-- Seed Data
INSERT INTO monuments (name, category, size_category, base_score, location) VALUES
('Mole Antonelliana', 'monument', 'large', 5.0, ST_SetSRID(ST_MakePoint(7.6931, 45.0689), 4326)),
('Palazzo Madama', 'historic_building', 'large', 4.8, ST_SetSRID(ST_MakePoint(7.6857, 45.0709), 4326)),
('Palazzo Reale', 'historic_building', 'large', 4.8, ST_SetSRID(ST_MakePoint(7.6860, 45.0722), 4326)),
('Galleria Subalpina', 'arcade', 'medium', 4.6, ST_SetSRID(ST_MakePoint(7.6860, 45.0694), 4326)),
('Galleria San Federico', 'arcade', 'medium', 4.5, ST_SetSRID(ST_MakePoint(7.6828, 45.0681), 4326)),
('Monumento a Emanuele Filiberto', 'statue', 'small', 3.8, ST_SetSRID(ST_MakePoint(7.6825, 45.0664), 4326))
ON CONFLICT DO NOTHING;

INSERT INTO featured_streets (name, score) VALUES
('Via Po', 4.8),
('Via Roma', 4.7),
('Via Lagrange', 4.5),
('Via Carlo Alberto', 4.4),
('Via Giuseppe Garibaldi', 4.2)
ON CONFLICT (name) DO NOTHING;

INSERT INTO featured_piazzas (name) VALUES
('Piazza Castello'),
('Piazza San Carlo'),
('Piazza Vittorio Veneto'),
('Piazza Carignano')
ON CONFLICT (name) DO NOTHING;