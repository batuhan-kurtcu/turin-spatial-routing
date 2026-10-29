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
-- used EWKT syntax as we its the standard dbeaver syntax
INSERT INTO public.monuments ("name",category,size_category,base_score,"location") VALUES
	 ('Mole Antonelliana','monument','large',5.0,'SRID=4326;POINT (7.6931 45.0689)'::public.geometry),
	 ('Palazzo Madama','historic_building','large',4.8,'SRID=4326;POINT (7.6857 45.0709)'::public.geometry),
	 ('Palazzo Reale','historic_building','large',4.8,'SRID=4326;POINT (7.686 45.0722)'::public.geometry),
	 ('Galleria San Federico','arcade','medium',4.5,'SRID=4326;POINT (7.6828 45.0681)'::public.geometry),
	 ('Arco monumentale all''Arma di Artiglieria ','statue','small',3.8,'SRID=4326;POINT (7.69058 45.058284)'::public.geometry),
	 ('Castello del Valentino','castle','large',5.0,'SRID=4326;POINT (7.686911 45.054053)'::public.geometry),
	 ('Ponte Umberto I','bridge','large',4.5,'SRID=4326;POINT (7.692007 45.058032)'::public.geometry),
	 ('Galleria Subalpina','arcade','medium',5.0,'SRID=4326;POINT (7.686 45.0694)'::public.geometry),
	 ('Monumento a Emanuele Filiberto','statue','small',5.0,'SRID=4326;POINT (7.6825 45.0664)'::public.geometry);
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


