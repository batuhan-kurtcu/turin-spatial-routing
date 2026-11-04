"""PostGIS Data Loading Pipeline for Turin Spatial Routing.

This script manages database initialization and loads spatial data into PostGIS:
1. Database schema and PostGIS extension initialization
2. Cultural landmarks, monuments, featured streets, and piazzas (from data/landmarks.json - SSOT)
3. OSM Amenities (cafes, restaurants, points of interest) for scenic scoring
4. OSM Walking Network nodes & edges for spatial queries and routing analysis

Usage:
    # 1. Start database container first:
    docker compose up -d

    # 2. Run data loader (populates from landmarks.json):
    py data-pipeline/load_to_postgis.py

    # Optional flags:
    py data-pipeline/load_to_postgis.py --all
    py data-pipeline/load_to_postgis.py --amenities
    py data-pipeline/load_to_postgis.py --network
    py data-pipeline/load_to_postgis.py --recreate
"""

import argparse
import json
import os
import sys
from typing import Optional

# Ensure safe UTF-8 output on Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import geopandas as gpd
import pandas as pd
from dotenv import load_dotenv
from shapely.geometry import Point
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Define base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LANDMARKS_JSON_PATH = os.path.join(DATA_DIR, "landmarks.json")
INIT_SQL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "init_db.sql")
PBF_PATH = os.path.join(BASE_DIR, "nord-ovest-latest.osm.pbf")
BBOX_PYROSM = [7.6650, 45.0580, 7.6980, 45.0800]  # Turin Centro Bounding Box

# Load environment variables
load_dotenv(os.path.join(BASE_DIR, ".env"))


def get_db_uri() -> str:
    """Builds and returns the PostgreSQL/PostGIS connection URI from environment variables."""
    if os.getenv("POSTGIS_URI"):
        return os.getenv("POSTGIS_URI")

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    # On Windows, 127.0.0.1 prevents IPv6 (::1) lookup hangs when binding to 127.0.0.1
    if host == "localhost":
        host = "127.0.0.1"

    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "postgres")

    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def get_db_engine(db_uri: Optional[str] = None) -> Engine:
    """Creates a SQLAlchemy engine with a timeout and verifies connectivity."""
    uri = db_uri or get_db_uri()
    try:
        # connect_timeout=5 ensures it fails fast if PostGIS/Docker is not running
        engine = create_engine(
            uri,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
        return engine
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ [ERROR] Could not connect to PostGIS at:")
        print(f"   {uri}")
        print("=" * 60)
        print("\nTroubleshooting steps:")
        print(" 1. Make sure Docker Desktop is started.")
        print(" 2. Start the PostGIS database container by running:")
        print("       docker compose up -d")
        print(" 3. Verify the container is running with:")
        print("       docker ps")
        print(" 4. Verify your .env credentials match docker-compose.yml.\n")
        print(f"Error details: {e}\n")
        sys.exit(1)


def init_schema(engine: Engine, drop_existing: bool = False) -> None:
    """Initializes PostGIS extension and core tables."""
    print("🔧 Initializing PostGIS extensions and schemas...")

    with engine.begin() as conn:
        # Enable PostGIS extension
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))

        if drop_existing:
            print("  ⚠️ Dropping existing tables (--recreate specified)...")
            conn.execute(text("DROP TABLE IF EXISTS monuments CASCADE;"))
            conn.execute(text("DROP TABLE IF EXISTS featured_streets CASCADE;"))
            conn.execute(text("DROP TABLE IF EXISTS featured_piazzas CASCADE;"))
            conn.execute(text("DROP TABLE IF EXISTS amenities CASCADE;"))
            conn.execute(text("DROP TABLE IF EXISTS turin_network_edges CASCADE;"))
            conn.execute(text("DROP TABLE IF EXISTS turin_network_nodes CASCADE;"))

        # Create monuments table (with height for 2.5D viewshed / isovists)
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS monuments (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    category VARCHAR(100),
                    size_category VARCHAR(50),
                    base_score NUMERIC(3, 1),
                    height NUMERIC(5, 1),
                    geometry GEOMETRY(Point, 4326)
                );
                CREATE INDEX IF NOT EXISTS monuments_geom_idx 
                ON monuments USING GIST (geometry);
                """
            )
        )

        # Create featured streets table
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS featured_streets (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    score NUMERIC(3, 1)
                );
                """
            )
        )

        # Create featured piazzas table
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS featured_piazzas (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE
                );
                """
            )
        )

    print("✅ Schema initialized successfully.")


def load_landmarks(engine: Engine, json_path: str = LANDMARKS_JSON_PATH) -> None:
    """Loads monuments, featured streets, and featured piazzas from landmarks.json into PostGIS."""
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"[ERROR] Landmarks JSON file not found at: {json_path}")

    print(f"📖 Loading landmark data from {json_path} (Single Source of Truth)...")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Load monuments
    monuments_list = data.get("monuments", [])
    if monuments_list:
        monuments_records = []
        for m in monuments_list:
            lat = float(m["lat"])
            lon = float(m["lon"])
            geom = Point(lon, lat)  # Lon (x), Lat (y) in EPSG:4326
            monuments_records.append(
                {
                    "name": m.get("name"),
                    "category": m.get("category"),
                    "size_category": m.get("size_category", "medium"),
                    "base_score": float(m.get("base_score", 3.0)),
                    "height": float(m["height"]) if "height" in m and m["height"] is not None else None,
                    "geometry": geom,
                }
            )

        gdf_monuments = gpd.GeoDataFrame(monuments_records, crs="EPSG:4326")

        with engine.begin() as conn:
            for _, row in gdf_monuments.iterrows():
                stmt = text(
                    """
                    INSERT INTO monuments (name, category, size_category, base_score, height, geometry)
                    VALUES (:name, :category, :size_category, :base_score, :height, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                    ON CONFLICT (name) DO UPDATE 
                    SET category = EXCLUDED.category,
                        size_category = EXCLUDED.size_category,
                        base_score = EXCLUDED.base_score,
                        height = EXCLUDED.height,
                        geometry = EXCLUDED.geometry;
                    """
                )
                conn.execute(
                    stmt,
                    {
                        "name": row["name"],
                        "category": row["category"],
                        "size_category": row["size_category"],
                        "base_score": row["base_score"],
                        "height": row["height"],
                        "lon": row["geometry"].x,
                        "lat": row["geometry"].y,
                    },
                )
        print(f"  🏛️ Loaded/Updated {len(gdf_monuments)} monuments.")

    # 2. Load featured streets
    featured_streets = data.get("featured_streets", {})
    if featured_streets:
        with engine.begin() as conn:
            for street_name, score in featured_streets.items():
                stmt = text(
                    """
                    INSERT INTO featured_streets (name, score)
                    VALUES (:name, :score)
                    ON CONFLICT (name) DO UPDATE
                    SET score = EXCLUDED.score;
                    """
                )
                conn.execute(stmt, {"name": street_name.strip(), "score": float(score)})
        print(f"  🛣️ Loaded/Updated {len(featured_streets)} featured streets.")

    # 3. Load featured piazzas
    featured_piazzas = data.get("featured_piazzas", [])
    if featured_piazzas:
        with engine.begin() as conn:
            for piazza_name in featured_piazzas:
                stmt = text(
                    """
                    INSERT INTO featured_piazzas (name)
                    VALUES (:name)
                    ON CONFLICT (name) DO NOTHING;
                    """
                )
                conn.execute(stmt, {"name": piazza_name.strip()})
        print(f"  ⛲ Loaded/Updated {len(featured_piazzas)} featured piazzas.")


def load_amenities(engine: Engine, pbf_path: str = PBF_PATH, bbox: list = BBOX_PYROSM) -> None:
    """Extracts cafes, restaurants, and amenities from OSM PBF and stores them in PostGIS."""
    if not os.path.exists(pbf_path):
        print(f"  ⚠️ Skipping amenities: PBF file not found at {pbf_path}")
        return

    print("☕ Extracting amenities (cafes, bars, restaurants) from local PBF...")
    try:
        from pyrosm import OSM

        osm = OSM(pbf_path, bounding_box=bbox)
        custom_filter = {"amenity": ["cafe", "restaurant", "bar", "pub", "ice_cream"]}
        pois = osm.get_pois(custom_filter=custom_filter)

        if pois is None or pois.empty:
            print("  ⚠️ No amenities found in the designated bounding box.")
            return

        # Ensure Point geometries
        pois["geometry"] = pois["geometry"].apply(
            lambda geom: geom.centroid if geom and geom.geom_type != "Point" else geom
        )
        pois = pois.dropna(subset=["geometry"])

        # Filter down columns
        keep_cols = ["id", "name", "amenity", "geometry"]
        avail_cols = [c for c in keep_cols if c in pois.columns]
        pois_clean = pois[avail_cols].copy()

        # Clean string/list types
        for col in pois_clean.columns:
            if col != "geometry":
                pois_clean[col] = pois_clean[col].astype(str)

        print(f"  💾 Writing {len(pois_clean):,} amenities to PostGIS table 'amenities'...")
        pois_clean.to_postgis(
            "amenities",
            engine,
            if_exists="replace",
            index=False,
            schema="public",
        )

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS amenities_geom_idx 
                    ON amenities USING GIST (geometry);
                    """
                )
            )

        print(f"  ✅ Saved {len(pois_clean):,} amenities to PostGIS.")

    except ImportError:
        print("  ⚠️ pyrosm not installed or available, skipping amenities extraction.")
    except Exception as e:
        print(f"  ⚠️ Error extracting/loading amenities: {e}")


def load_network(engine: Engine) -> None:
    """Extracts walking network graph and loads edges & nodes into PostGIS."""
    print("🚶 Extracting walking network graph from local PBF...")
    try:
        import osmnx as ox
        from extract_osm import extract_turin_graph

        G = extract_turin_graph()

        print("  🔄 Converting graph to WGS84 GeoDataFrames...")
        G_wgs84 = ox.project_graph(G, to_crs="EPSG:4326")
        nodes_gdf, edges_gdf = ox.graph_to_gdfs(G_wgs84)

        # Helper to sanitize dataframe columns with unhashable types (lists/dicts)
        def clean_gdf_for_sql(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
            gdf = gdf.copy().reset_index()
            for col in gdf.columns:
                if col == "geometry":
                    continue
                if gdf[col].apply(lambda v: isinstance(v, (list, dict))).any():
                    gdf[col] = gdf[col].apply(lambda v: ", ".join(map(str, v)) if isinstance(v, list) else str(v))
            return gdf

        nodes_clean = clean_gdf_for_sql(nodes_gdf)
        edges_clean = clean_gdf_for_sql(edges_gdf)

        print(f"  💾 Writing {len(nodes_clean):,} nodes to PostGIS table 'turin_network_nodes'...")
        nodes_clean.to_postgis(
            "turin_network_nodes",
            engine,
            if_exists="replace",
            index=False,
            schema="public",
        )

        print(f"  💾 Writing {len(edges_clean):,} edges to PostGIS table 'turin_network_edges'...")
        edges_clean.to_postgis(
            "turin_network_edges",
            engine,
            if_exists="replace",
            index=False,
            schema="public",
        )

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS turin_nodes_geom_idx 
                    ON turin_network_nodes USING GIST (geometry);
                    CREATE INDEX IF NOT EXISTS turin_edges_geom_idx 
                    ON turin_network_edges USING GIST (geometry);
                    """
                )
            )

        print(f"  ✅ Saved walking network ({len(nodes_clean):,} nodes, {len(edges_clean):,} edges) to PostGIS.")

    except Exception as e:
        print(f"  ⚠️ Error extracting/loading walking network: {e}")


def execute_sql_file(engine: Engine, sql_file_path: str = INIT_SQL_PATH) -> None:
    """Executes a raw SQL file (e.g. init_db.sql) directly on PostGIS."""
    if not os.path.exists(sql_file_path):
        raise FileNotFoundError(f"[ERROR] SQL file not found at: {sql_file_path}")

    print(f"📄 Executing SQL script: {sql_file_path}...")
    with open(sql_file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # Split statements safely by semicolon
    statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]

    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                print(f"  ⚠️ Warning on SQL statement execution: {e}")

    print("✅ SQL script executed successfully.")


def main():
    parser = argparse.ArgumentParser(
        description="Load spatial data, cultural landmarks, and network graphs into PostGIS for Turin Routing."
    )
    parser.add_argument(
        "--landmarks",
        action="store_true",
        help="Load cultural monuments, featured streets, and piazzas from landmarks.json.",
    )
    parser.add_argument(
        "--amenities",
        action="store_true",
        help="Extract cafes and points of interest from OSM PBF and load to PostGIS.",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Extract walking network nodes and edges and load to PostGIS.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Load landmarks, amenities, and network graph.",
    )
    parser.add_argument(
        "--init-sql",
        action="store_true",
        help="Execute init_db.sql file directly.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate existing tables before loading.",
    )

    args = parser.parse_args()

    # Default behavior if no specific flags provided: load landmarks
    if not (args.landmarks or args.amenities or args.network or args.all or args.init_sql):
        args.landmarks = True

    print("=" * 60)
    print("🚀 TURIN SPATIAL ROUTING - POSTGIS DATA LOADER")
    print("=" * 60)

    engine = get_db_engine()
    print(f"🔌 Connected to PostGIS: {engine.url.database}@{engine.url.host}")

    if args.init_sql:
        execute_sql_file(engine)
    else:
        init_schema(engine, drop_existing=args.recreate)

        if args.landmarks or args.all:
            load_landmarks(engine)

        if args.amenities or args.all:
            load_amenities(engine)

        if args.network or args.all:
            load_network(engine)

        print("\n🎉 All requested PostGIS data loads completed successfully!")


if __name__ == "__main__":
    main()
