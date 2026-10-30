import os
import webbrowser
import folium
import osmnx as ox
from pyrosm import OSM

from compute_scenic_scores import compute_graph_scenic_scores

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PBF_PATH = os.path.join(BASE_DIR, "nord-ovest-latest.osm.pbf")
BBOX_PYROSM = [7.6650, 45.0580, 7.6980, 45.0800]

#Note: everystep will be printed to inform us the specific point where the problem occurs

def get_score_color(score: float) -> str:
    """Maps a 1.0 - 5.0 scenic score to a color hex code."""
    if score >= 4.5:
        return "#FFD700"  
    elif score >= 3.5:
        return "#2ECC71"  
    elif score >= 2.5:
        return "#3498DB"   
    return  "#BDC3C7"  
      


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
        "6. Step B: Consolidating complex multi-node intersections (15m tolerance)..."
    )
    G_consolidated = ox.consolidate_intersections(
        G_simple, rebuild_graph=True, tolerance=15, dead_ends=False
    )

    print("7. Computing 1.0 - 5.0 scenic scores using compute_scenic_scores.py...")
    G_scored = compute_graph_scenic_scores(G_consolidated)

    print("8. Reprojecting back to WGS84 for map display...")
    G_latlon = ox.project_graph(G_scored, to_crs="EPSG:4326")
    nodes_simple, edges_simple = ox.graph_to_gdfs(G_latlon)

    # removing parallel duplicate edges (walking paths)
    def extract_scalar(val, default):
        if isinstance(val, list):
            return val[0] if val else default
        return val if val is not None else default

    edges_simple["scenic_score_clean"] = edges_simple["scenic_score"].apply(lambda v: float(extract_scalar(v, 1.0)))
    edges_simple["name_clean"] = edges_simple["name"].apply(lambda v: str(extract_scalar(v, "Unnamed Street")))
    edges_simple["highway_clean"] = edges_simple["highway"].apply(lambda v: str(extract_scalar(v, "N/A")))


    #discarding duplicate entries
    edges_unique = edges_simple.reset_index()
    if "u" in edges_unique.columns and "v" in edges_unique.columns:
        edges_unique = edges_unique.drop_duplicates(subset=["u", "v"])

    print("9. Building Folium map...")
    m = folium.Map(location=[45.0690, 7.6815], zoom_start=15, tiles="OpenStreetMap")


    folium.GeoJson(
        edges_unique[["name_clean", "highway_clean", "scenic_score_clean", "geometry"]],
        tooltip=folium.GeoJsonTooltip(
            fields=["name_clean", "highway_clean", "scenic_score_clean"],
            aliases=["Street:", "Type:", "Scenic Score:"]
        ),
        style_function=lambda feature: {
            "color": get_score_color(feature["properties"]["scenic_score_clean"]),
            "weight": 3.5 if feature["properties"]["scenic_score_clean"] >= 3.5 else 2.0,
            "opacity": 0.85,
        },
    ).add_to(m)

    for _, node in nodes_simple.iterrows():
        folium.CircleMarker(
            location=[node.geometry.y, node.geometry.x],
            radius=1.5,
            color="#e74c3c",
            fill=True,
            fill_color="#e74c3c",
            fill_opacity=0.6,
            tooltip=f"Node ID: {node.get('osmid', 'N/A')}",
        ).add_to(m)

    #adding visual color key legend to the map
    legend_html = """
     <div style="position: fixed; bottom: 30px; left: 30px; width: 190px; height: 135px; 
                 border:2px solid grey; z-index:9999; font-size:13px; background-color:white;
                 padding: 10px; border-radius: 5px; opacity: 0.9;">
     <b>Scenic Score Ratings</b><br>
     <i style="background:#FFD700; width:12px; height:12px; float:left; margin-right:8px; margin-top:3px;"></i> 4.5 - 5.0 (Iconic)<br>
     <i style="background:#2ECC71; width:12px; height:12px; float:left; margin-right:8px; margin-top:3px;"></i> 3.5 - 4.4 (Very Scenic)<br>
     <i style="background:#3498DB; width:12px; height:12px; float:left; margin-right:8px; margin-top:3px;"></i> 2.5 - 3.4 (Pleasant)<br>
     <i style="background:#BDC3C7; width:12px; height:12px; float:left; margin-right:8px; margin-top:3px;"></i> 1.0 - 2.4 (Standard)<br>
     </div>
     """
    m.get_root().html.add_child(folium.Element(legend_html))

    output_path = os.path.join(BASE_DIR, "data", "turin_edges_inspector.html")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    m.save(output_path)
    print(f"Clean consolidated inspection map saved to: {output_path}")

    #opening local server URL directly
    #make sure to start:  python -m http.server 8000 on another terminal
    webbrowser.open("http://localhost:8000/data/turin_edges_inspector.html")


if __name__ == "__main__":
    generate_inspection_map()