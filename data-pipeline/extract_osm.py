import os
import osmnx as ox
from pyrosm import OSM

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PBF_PATH = os.path.join(BASE_DIR, "nord-ovest-latest.osm.pbf")
LOCAL_CRS = "EPSG:32632"
BBOX_PYROSM = [7.6650, 45.0580, 7.6980, 45.0800]  # Turin Centro Bounding Box


def extract_turin_graph():
    """Extracts and projects walking network graph from local .pbf file."""
    if not os.path.exists(PBF_PATH):
        raise FileNotFoundError(
            f"[CRITICAL] {PBF_PATH} not found in root directory!"
        )

    print("Reading local nord-ovest-latest.osm.pbf and clipping to Turin Centro...")
    osm = OSM(PBF_PATH, bounding_box=BBOX_PYROSM)

    nodes_gdf, edges_gdf = osm.get_network(network_type="walking", nodes=True)

    # Use graph_type="networkx" to get a NetworkX MultiDiGraph directly
    G = osm.to_graph(nodes_gdf, edges_gdf, graph_type="networkx")

    # Set WGS84 CRS so OSMnx knows how to project it
    G.graph["crs"] = "EPSG:4326"

    # Project to local metric system EPSG:32632
    G_projected = ox.project_graph(G, to_crs=LOCAL_CRS)

    # Add default walking speeds and travel times
    G_projected = ox.add_edge_speeds(G_projected, fallback=4.5)
    G_projected = ox.add_edge_travel_times(G_projected)

    print(
        f" Loaded {len(G_projected.nodes):,} nodes and {len(G_projected.edges):,} edges from local .pbf."
    )
    return G_projected


if __name__ == "__main__":
    extract_turin_graph()