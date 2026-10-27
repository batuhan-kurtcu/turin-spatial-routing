import osmnx as ox

# Define bounding box for Turin
# Note: OSMnx 1.x vs 2.x uses bbox parameter order or bbox tuple.
# For OSMnx v2.0+: bbox=(west, south, east, north)
# For older OSMnx: bbox=(north, south, east, west)
north, south, east, west = 45.12, 45.00, 7.75, 7.57

# 1. Fetch 2.5D visual layers
building_tags = {
    "building": True,
    "building:levels": True,
    "height": True,
    "landuse": True,
    "leisure": True,
    "waterway": True,
    "amenity": True
}

gdf_buildings = ox.features_from_bbox(
    bbox=(north, south, east, west),
    tags=building_tags
)

# 2. Fetch routing network (automatically grabs all footways/paths)
G_walk = ox.graph_from_bbox(
    bbox=(north, south, east, west),
    network_type="walk"
)