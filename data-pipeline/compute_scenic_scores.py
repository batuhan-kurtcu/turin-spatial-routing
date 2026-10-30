#import json
import os
import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB_URI = os.getenv(
    "POSTGIS_URI", 
    "postgresql://postgres:postgres@127.0.0.1:5432/turin_map"
)

#exponential decay with lambda values for every size category
#it feels good to use things i learned at lectures finally
DECAY_PARAMS = {
    "large":  {"max_dist": 350.0, "lambda": 0.005},  
    "medium": {"max_dist": 200.0, "lambda": 0.010},  
    "small":  {"max_dist": 80.0,  "lambda": 0.020},  
}

MAX_DECAY_RADIUS = 350.0  #upper bound of decays

DEFAULT_DB_URI = os.getenv(
    "POSTGIS_URI", 
    "postgresql://postgres:postgres@127.0.0.1:5432/turin_map"
)

#.-.-.-.-.-.-.-.-.-.-.
#postgis data loading
#.-.-.-.-.-.-.-.-.-.-.

def load_landmarks_from_postgis(
    engine, 
    table_name: str = "monuments", 
    target_crs: str = "EPSG:32632"
) -> gpd.GeoDataFrame:
    """Queries landmark points from PostGIS and reprojects to EPSG:32632."""
    try:
        query = f"SELECT id, name, size_category, base_score, geometry FROM {table_name};"
        with engine.connect() as conn:
            gdf = gpd.read_postgis(sql=query, con=conn, geom_col="geometry", crs="EPSG:4326")
        
        if gdf.empty:
            print(f" Warning: Table '{table_name}' returned zero records.")
            return gpd.GeoDataFrame(
                columns=["id", "name", "size_category", "base_score", "geometry"], 
                crs=target_crs
            )
        return gdf.to_crs(target_crs)
    except Exception as e:
        print(f" Could not load '{table_name}' table from PostGIS: {e}")
        return gpd.GeoDataFrame(
            columns=["id", "name", "size_category", "base_score", "geometry"], 
            crs=target_crs
        )


def load_featured_streets_from_postgis(engine, table_name: str = "featured_streets") -> dict:
    """Queries featured streets table and returns lowercased lookup dict: {street_name: score}."""
    try:
        with engine.connect() as conn:
            df = pd.read_sql_query(f"SELECT name, score FROM {table_name};", conn)
        if df.empty:
            return {}
        
        return {str(name).strip().lower(): float(score) for name, score in zip(df["name"], df["score"]) if name}
    except Exception as e:
        print(f" Could not load '{table_name}' table from PostGIS: {e}")
        return {}


def load_featured_piazzas_from_postgis(engine, table_name: str = "featured_piazzas") -> list:
    """Queries featured piazzas table and returns lowercased list of piazza names."""
    try:
        with engine.connect() as conn:
            df = pd.read_sql_query(f"SELECT name FROM {table_name};", conn)
        if df.empty:
            return []
        return [str(name).strip().lower() for name in df["name"].dropna() if name]
    except Exception as e:
        print(f" Could not load '{table_name}' table from PostGIS: {e}")
        return []

#.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.
#scenic score calc helper funcs
#.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.


def clean_street_name(name_attr) -> str:
    """Safely parses OSM street names into a clean, lowercased string."""
    if not name_attr:
        return ""
    if isinstance(name_attr, list):
        #flattening the list into a single string
        return " ".join([str(n).strip().lower() for n in name_attr if n])
    return str(name_attr).strip().lower()


def calculate_landmark_boost_spatial(edge_geom, landmarks_gdf: gpd.GeoDataFrame) -> float:
    """Calculates landmark boost using spatial indexing (sindex) for fast candidate lookup."""
    if landmarks_gdf.empty or edge_geom is None:
        return 0.0

    #bounding box query using spatial index (O(log L) search)
    minx, miny, maxx, maxy = edge_geom.bounds
    possible_matches_idx = list(
        landmarks_gdf.sindex.intersection(
            (minx - MAX_DECAY_RADIUS, miny - MAX_DECAY_RADIUS, maxx + MAX_DECAY_RADIUS, maxy + MAX_DECAY_RADIUS)
        )
    )

    if not possible_matches_idx:
        return 0.0

    candidate_landmarks = landmarks_gdf.iloc[possible_matches_idx]

    #computing exponential decay for candidate landmarks inside bounding box
    total_boost = 0.0
    for _, lm in candidate_landmarks.iterrows():
        dist = edge_geom.distance(lm.geometry)  #exact distance in EPSG:32632 coordinate system meters
        size_cat = lm.get("size_category", "medium")
        params = DECAY_PARAMS.get(size_cat, DECAY_PARAMS["medium"])

        if dist <= params["max_dist"]:
            base_s = lm.get("base_score", 3.0)
            contribution = (base_s / 5.0) * np.exp(-params["lambda"] * dist)
            total_boost += contribution

    #capping maximum landmark contribution at 2.5 because why not?
    return min(2.5, total_boost)


def calculate_final_score_headroom(base_score: float, lm_boost: float, cafe_boost: float) -> float:
    """Additive Headroom strategy: Applies boosts relative to remaining headroom up to 5.0."""
    raw_boost = lm_boost + cafe_boost
    headroom = max(0.0, (5.0 - base_score) / 4.0)
    adjusted_boost = raw_boost * headroom

    final_score = base_score + adjusted_boost
    return round(min(5.0, max(1.0, final_score)), 2)


#.-.-.-.-.-.-.-.-.-.-.
#pipeline entry point
#.-.-.-.-.-.-.-.-.-.-.

def compute_graph_scenic_scores(
    G: nx.MultiDiGraph,
    db_uri: str = DEFAULT_DB_URI,
    cafes_gdf: gpd.GeoDataFrame = None
) -> nx.MultiDiGraph:
    """Queries PostGIS tables and attaches scenic scores & edge costs to graph edges."""
    
    engine = create_engine(db_uri)
    
    #fetching postgis spatial features and tables
    landmarks_gdf = load_landmarks_from_postgis(engine, table_name="monuments")
    featured_streets = load_featured_streets_from_postgis(engine, table_name="featured_streets")
    featured_piazzas = load_featured_piazzas_from_postgis(engine, table_name="featured_piazzas")

    print(f" Loaded {len(landmarks_gdf)} monuments, {len(featured_streets)} featured streets, and {len(featured_piazzas)} featured piazzas.")

    #extracting edge geodataframe and project to EPSG:32632 for spatial joins
    edges_gdf = ox.graph_to_gdfs(G, nodes=False)
    if edges_gdf.crs is None or edges_gdf.crs != "EPSG:32632":
        edges_gdf = edges_gdf.to_crs("EPSG:32632")

    #iterate over edges and calculate scenic scores
    for u, v, k, data in G.edges(keys=True, data=True):
        length = float(data.get("length", 1.0))
        raw_name = data.get("name", "")
        street_name = clean_street_name(raw_name)

        #projected geometry from geodataframe
        geom = edges_gdf.loc[(u, v, k), "geometry"] if (u, v, k) in edges_gdf.index else data.get("geometry")

        #scoring system from 1 to 5
        base_score = 1.0
        if street_name in featured_streets:
            base_score = featured_streets[street_name]
        elif any(piazza in street_name for piazza in featured_piazzas if piazza):
            base_score = 4.8
        else:
            #fallback to openstreetmap structural tags
            if data.get("covered") in ["yes", "arcade"]:
                base_score += 0.8
            if data.get("highway") in ["pedestrian", "footway"]:
                base_score += 0.5
            if data.get("surface") in ["cobblestone", "paving_stones"]:
                base_score += 0.3

        #cafe density boost up to .5 
        #this also might backfire as the cafe densed streets are likely to be popular
        #can stay for now tho
        cafe_boost = 0.0
        if cafes_gdf is not None and not cafes_gdf.empty and geom is not None:
            buffer_zone = geom.buffer(25.0)
            nearby_cafes = cafes_gdf[cafes_gdf.geometry.within(buffer_zone)]
            cafe_boost = min(0.5, len(nearby_cafes) * 0.10)

        #spatial indexed landmark proximity boost
        lm_boost = calculate_landmark_boost_spatial(geom, landmarks_gdf)

        #additive headroom strat
        final_score = calculate_final_score_headroom(base_score, lm_boost, cafe_boost)

        #attaching graph attributes
        data["scenic_score"] = final_score
        data["weighted_scenic_len"] = final_score * length
        
        #pathfinder cost: higher score = lower edge weight 
        #0.1 is used just to save us from the 0 case
        data["scenic_cost"] = length / max(0.1, final_score)

    engine.dispose()
    print(" Scenic scoring across PostGIS tables completed successfully.")
    return G


if __name__ == "__main__":
    print(f"Scoring pipeline module ready using PostGIS URI: {DEFAULT_DB_URI}")