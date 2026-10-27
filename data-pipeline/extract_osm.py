import os
import osmnx as ox
from pyrosm import OSM

# 1. DYNAMIC FILE PATHS & SPATIAL SETTINGS
# Build path to root directory where nord-ovest-latest.osm.pbf lives
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PBF_PATH = os.path.join(BASE_DIR, "nord-ovest-latest.osm.pbf")

LOCAL_CRS = "EPSG:32632"  # Metric UTM Zone 32N for Turin
BBOX_PYROSM = [7.6650, 45.0580, 7.6980, 45.0800]  # [min_lon, min_lat, max_lon, max_lat]

# 2. EXTRACT & ROUTE PEDESTRIAN NETWORK
if not os.path.exists(PBF_PATH):
    print(f"Error: {PBF_PATH} not found in root directory!")
else:
    print("Reading local PBF file and clipping to Turin Centro...")
    osm = OSM(PBF_PATH, bounding_box=BBOX_PYROSM)

    # Extract walking network as GeoDataFrames
    nodes_gdf, edges_gdf = osm.get_network(network_type="walking", nodes=True)

    # Convert to NetworkX graph
    G = osm.to_graph(nodes_gdf, edges_gdf, network_type="walking")

    # Project graph to metric CRS (meters) FIRST before adding speeds
    G_projected = ox.project_graph(G, to_crs=LOCAL_CRS)

    # Add default walking speeds (4.5 km/h) and calculate travel times in seconds
    G_projected = ox.add_edge_speeds(G_projected, fallback=4.5)
    G_projected = ox.add_edge_travel_times(G_projected)

    # Convert back to projected GeoDataFrames for spatial analysis
    nodes_projected, edges_projected = ox.graph_to_gdfs(G_projected)

    print("\n--- Step 1 Execution Complete ---")
    print(f"Loaded {len(nodes_projected):,} nodes and {len(edges_projected):,} edges.")
    print(f"Coordinate Reference System: {edges_projected.crs}")