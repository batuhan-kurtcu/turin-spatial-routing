import os
import osmnx as ox
from pyrosm import OSM

# 1. Paths
pbf_path = "nord-ovest-latest.osm.pbf"
output_graphml = os.path.join("data", "turin_raw.graphml")

# 2. Define Turin Bounding Box [min_lon, min_lat, max_lon, max_lat]
bbox_turin = [7.57, 45.00, 7.75, 45.12]

print("Extracting Turin street network from regional PBF...")
osm = OSM(pbf_path, bounding_box=bbox_turin)

# 3. Extract walking network nodes and edges
nodes, edges = osm.get_network(network_type="walking", nodes=True)

# 4. Convert to NetworkX graph
G = osm.to_graph(nodes, edges, graph_type="networkx")

# 5. Save raw graph locally
os.makedirs("data", exist_ok=True)
ox.save_graphml(G, output_graphml)

print(f"Extraction complete! Saved raw Turin graph to: {output_graphml}")