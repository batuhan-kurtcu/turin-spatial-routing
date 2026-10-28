import json
import os
import geopandas as gpd
import networkx as nx
import numpy as np

# Exponential distance decay parameters based on physical size category
DECAY_PARAMS = {
    "large":  {"max_dist": 350.0, "lambda": 0.005},  # Smooth decay up to 350m
    "medium": {"max_dist": 200.0, "lambda": 0.010},  # Smooth decay up to 200m
    "small":  {"max_dist": 80.0,  "lambda": 0.020},  # Smooth decay up to 80m
}


def load_landmarks(json_path: str) -> gpd.GeoDataFrame:
    """Loads landmark JSON and converts monuments into projected GeoDataFrame (EPSG:32632)."""
    if not os.path.exists(json_path):
        print(f"Warning: Landmark config file '{json_path}' not found.")
        return gpd.GeoDataFrame(columns=["name", "geometry"], crs="EPSG:32632")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    landmarks_list = data.get("monuments", [])
    if not landmarks_list:
        return gpd.GeoDataFrame(columns=["name", "geometry"], crs="EPSG:32632")

    gdf = gpd.GeoDataFrame(
        landmarks_list,
        geometry=gpd.points_from_xy(
            [lm["lon"] for lm in landmarks_list],
            [lm["lat"] for lm in landmarks_list],
        ),
        crs="EPSG:4326",
    ).to_crs("EPSG:32632")

    return gdf


def calculate_landmark_boost(edge_geom, landmarks_gdf: gpd.GeoDataFrame) -> float:
    """Calculates landmark score boost using exponential distance decay."""
    if landmarks_gdf.empty or edge_geom is None:
        return 0.0

    total_boost = 0.0
    for _, lm in landmarks_gdf.iterrows():
        dist = edge_geom.distance(lm.geometry)
        size_cat = lm.get("size_category", "medium")
        params = DECAY_PARAMS.get(size_cat, DECAY_PARAMS["medium"])

        if dist <= params["max_dist"]:
            base_s = lm.get("base_score", 3.0)
            # Contribution decay formula
            contribution = (base_s / 5.0) * np.exp(-params["lambda"] * dist)
            total_boost += contribution

    # Cap maximum landmark contribution at +2.5
    return min(2.5, total_boost)


def calculate_final_score_headroom(base_score: float, lm_boost: float, cafe_boost: float) -> float:
    """Additive Headroom strategy:
    Applies boosts relative to remaining headroom up to 5.0.
    Prevents double-counting on featured streets while preserving 1.0 - 5.0 bounds.
    """
    raw_boost = lm_boost + cafe_boost
    
    # Headroom ratio: 1.0 when base=1.0, drops to 0.0 when base=5.0
    headroom = max(0.0, (5.0 - base_score) / 4.0)
    adjusted_boost = raw_boost * headroom

    final_score = base_score + adjusted_boost
    return round(min(5.0, max(1.0, final_score)), 2)


def compute_graph_scenic_scores(
    G: nx.MultiDiGraph,
    config_json_path: str,
    cafes_gdf: gpd.GeoDataFrame = None
) -> nx.MultiDiGraph:
    """Computes final 1.0 - 5.0 scenic ratings and pathfinding edge costs."""
    
    # Load landmarks and street overrides
    landmarks_gdf = load_landmarks(config_json_path)
    
    featured_streets = {}
    featured_piazzas = []
    if os.path.exists(config_json_path):
        with open(config_json_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            featured_streets = config.get("featured_streets", {})
            featured_piazzas = config.get("featured_piazzas", [])

    for u, v, k, data in G.edges(keys=True, data=True):
        length = data.get("length", 1.0)
        geom = data.get("geometry")
        street_name = data.get("name", "")

        if isinstance(street_name, list):
            street_name = street_name[0] if street_name else ""

        # 1. Establish Base Score (1.0 - 5.0 scale)
        base_score = 1.0
        if street_name in featured_streets:
            base_score = featured_streets[street_name]
        elif any(piazza in str(street_name) for piazza in featured_piazzas):
            base_score = 4.8
        else:
            # Fallback to OSM tags
            if data.get("covered") in ["yes", "arcade"]:
                base_score += 0.8
            if data.get("highway") in ["pedestrian", "footway"]:
                base_score += 0.5
            if data.get("surface") in ["cobblestone", "paving_stones"]:
                base_score += 0.3

        # 2. Café Density Boost (up to +0.5)
        cafe_boost = 0.0
        if cafes_gdf is not None and not cafes_gdf.empty and geom is not None:
            buffer_zone = geom.buffer(25.0)
            nearby_cafes = cafes_gdf[cafes_gdf.geometry.within(buffer_zone)]
            cafe_boost = min(0.5, len(nearby_cafes) * 0.10)

        # 3. Landmark Proximity Boost
        lm_boost = calculate_landmark_boost(geom, landmarks_gdf)

        # 4. Apply Additive Headroom Strategy
        final_score = calculate_final_score_headroom(base_score, lm_boost, cafe_boost)

        # 5. Attach Graph Attributes
        data["scenic_score"] = final_score
        data["weighted_scenic_len"] = final_score * length
        
        # Pathfinder cost: higher score = lower edge weight
        data["scenic_cost"] = length / final_score

    print("Scenic scoring completed successfully.")
    return G


if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    CONFIG_PATH = os.path.join(BASE_DIR, "data", "landmarks.json")
    print(f"Scoring pipeline module ready using config: {CONFIG_PATH}")