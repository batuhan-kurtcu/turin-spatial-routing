import os
import osmnx as ox
from pyrosm import OSM

# building a path to our local .pbf file directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PBF_PATH = os.path.join(BASE_DIR, "nord-ovest-latest.osm.pbf")

#current .pbf file has the general north-west italy map which is around .566 gb
#we aim to cut it down to striclty the centro area of Turin for now (also includes small adjacent areas)


LOCAL_CRS = "EPSG:32632"  # italian/european metric system
BBOX_PYROSM = [7.6650, 45.0580, 7.6980, 45.0800]  # [min_lon, min_lat, max_lon, max_lat]

# 2. route + pedesterian path extraction
if not os.path.exists(PBF_PATH):
    print(f"Error: {PBF_PATH} not found in root directory!")
else:
    print("Reading local .pbf file and clipping to Turin Centro...")
    osm = OSM(PBF_PATH, bounding_box=BBOX_PYROSM)

    # extracting walking network as GeoDataFrames
    nodes_gdf, edges_gdf = osm.get_network(network_type="walking", nodes=True)

    # converting it to NetworkX graph
    G = osm.to_graph(nodes_gdf, edges_gdf, network_type="walking")

    # metric system projection
    G_projected = ox.project_graph(G, to_crs=LOCAL_CRS)

    # default walking speed is 4.5 km/h
    # travel times are in seconds 
    G_projected = ox.add_edge_speeds(G_projected, fallback=4.5)
    G_projected = ox.add_edge_travel_times(G_projected)

    # converting back to projected GeoDataFrames 
    nodes_projected, edges_projected = ox.graph_to_gdfs(G_projected)

    print("\n--- Step 1 Execution Complete ---")
    print(f"Loaded {len(nodes_projected):,} nodes and {len(edges_projected):,} edges.")
    print(f"Coordinate Reference System: {edges_projected.crs}")
