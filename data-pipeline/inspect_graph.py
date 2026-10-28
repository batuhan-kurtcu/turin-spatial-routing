import os
import folium
import osmnx as ox
from pyrosm import OSM

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PBF_PATH = os.path.join(BASE_DIR, "nord-ovest-latest.osm.pbf")
BBOX_PYROSM = [7.6650, 45.0580, 7.6980, 45.0800]

#Note: everystep will be printed to inform us the specific point where the problem occurs

def generate_inspection_map():
    print("1. Extracting raw network from PBF...")
    osm = OSM(PBF_PATH, bounding_box=BBOX_PYROSM)
    nodes_gdf, edges_gdf = osm.get_network(network_type="walking", nodes=True)

    print("2. Formatting GeoDataFrames for OSMnx...")
    nodes_gdf["x"] = nodes_gdf.geometry.x
    nodes_gdf["y"] = nodes_gdf.geometry.y

    for col in nodes_gdf.columns:
        if nodes_gdf[col].apply(lambda v: isinstance(v, (dict, list))).any():
            nodes_gdf[col] = nodes_gdf[col].astype(str)

    if "id" in nodes_gdf.columns:
        nodes_gdf = nodes_gdf.set_index("id")

    if "u" in edges_gdf.columns and "v" in edges_gdf.columns:
        if "key" not in edges_gdf.columns:
            edges_gdf["key"] = 0
        edges_gdf = edges_gdf.set_index(["u", "v", "key"])

    print("3. Converting GeoDataFrames to OSMnx graph...")
    G = ox.graph_from_gdfs(nodes_gdf, edges_gdf)
    G.graph["crs"] = "EPSG:4326"

    print("4. Projecting graph to metric CRS (EPSG:32632)...")
    G_projected = ox.project_graph(G, to_crs="EPSG:32632")

    print("5. Step A: Simplifying straight-line geometry nodes...")
    G_simple = ox.simplify_graph(G_projected)


    print(
        "6. Step B: Consolidating complex multi-node intersections (10m tolerance)..."
    )
    G_consolidated = ox.consolidate_intersections(
        G_simple, rebuild_graph=True, tolerance=10, dead_ends=False
    )

    print("7. Reprojecting back to WGS84 for map display...")
    G_latlon = ox.project_graph(G_consolidated, to_crs="EPSG:4326")
    nodes_simple, edges_simple = ox.graph_to_gdfs(G_latlon)

    print("8. Building Folium map...")
    m = folium.Map(location=[45.0690, 7.6815], zoom_start=15, tiles="OpenStreetMap")

    folium.GeoJson(
        edges_simple[["name", "highway", "geometry"]],
        tooltip=folium.GeoJsonTooltip(
            fields=["name", "highway"], aliases=["Street:", "Type:"]
        ),
        style_function=lambda x: {"color": "#3388ff", "weight": 2.5, "opacity": 0.8},
    ).add_to(m)

    for _, node in nodes_simple.iterrows():
        folium.CircleMarker(
            location=[node.geometry.y, node.geometry.x],
            radius=2.0,
            color="#e74c3c",
            fill=True,
            fill_color="#e74c3c",
            fill_opacity=0.7,
            tooltip=f"Node ID: {node.get('osmid', 'N/A')}",
        ).add_to(m)

    output_path = os.path.join(BASE_DIR, "turin_edges_inspector.html")
    m.save(output_path)
    print(f"Clean consolidated inspection map saved to: {output_path}")


if __name__ == "__main__":
    generate_inspection_map()