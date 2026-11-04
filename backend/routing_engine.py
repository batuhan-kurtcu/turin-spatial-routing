import heapq
import math
import networkx as nx
from typing import Dict, Any, Tuple, Optional

#------------------------------

# Helper and geometry functions

#------------------------------


def _normalize_landmark_id(landmark_attr: Any) -> Optional[str]:
    """Normalizes landmark IDs to string format to prevent type mismatch in frozenset operations."""
    if landmark_attr is None:
        return None
    val_str = str(landmark_attr).strip()
    return val_str if val_str and val_str.lower() != "none" else None


def get_node_coords(node_data: Dict[str, Any]) -> Tuple[float, float]:
    """Extracts (x, y) / (lon, lat) coordinates reliably from node attribute dicts."""
    x = node_data.get("x", node_data.get("lon"))
    y = node_data.get("y", node_data.get("lat"))

    if (x is None or y is None) and "geometry" in node_data:
        geom = node_data["geometry"]
        x, y = geom.x, geom.y

    if x is None or y is None:
        raise KeyError(f"[CRITICAL] Node missing spatial coordinates: {node_data}")

    return float(x), float(y)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates exact great-circle distance between two points on earth in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def calculate_heading(node_a_data: Dict[str, Any], node_b_data: Dict[str, Any]) -> float:
    """Calculates compass heading angle (0-360 deg) from Node A to Node B."""
    ax, ay = get_node_coords(node_a_data)
    bx, by = get_node_coords(node_b_data)
    return math.degrees(math.atan2(bx - ax, by - ay)) % 360


def calculate_turn_angle(heading1: float, heading2: float) -> float:
    """Calculates absolute turn angle change (0 to 180 degrees) between two headings."""
    diff = abs(heading1 - heading2) % 360
    return diff if diff <= 180 else 360 - diff


def network_bounded_heuristic(u: Any, v: Any, G: nx.Graph, walking_speed: float, manhattan_factor: float = 1.3) -> float:
    """Calculates minimum travel time to target using exact Haversine or Planar distance."""
    ux, uy = get_node_coords(G.nodes[u])
    vx, vy = get_node_coords(G.nodes[v])

    if -180.0 <= ux <= 180.0 and -90.0 <= uy <= 90.0:
        euclidean_dist = haversine_distance(uy, ux, vy, vx)
    else:
        euclidean_dist = math.sqrt((ux - vx) ** 2 + (uy - vy) ** 2)

    return (euclidean_dist * manhattan_factor) / walking_speed


def extract_best_edge_attributes(edge_data: Any) -> Dict[str, Any]:
    """Evaluates all parallel edges in a MultiDiGraph and picks the optimal edge."""
    if not isinstance(edge_data, dict):
        return {}

    if "length" in edge_data or "scenic_score" in edge_data:
        return edge_data

    best_attr = None
    best_ratio = -1.0
    min_length = float("inf")

    for _, attr in edge_data.items():
        if isinstance(attr, dict):
            score = float(attr.get("scenic_score", 0.0))
            length = float(attr.get("length", 1.0))
            ratio = score / max(length, 0.1)

            if ratio > best_ratio or (ratio == best_ratio and length < min_length):
                best_ratio = ratio
                min_length = length
                best_attr = attr

    return best_attr if best_attr is not None else {}


def build_component_map(G: nx.Graph) -> Dict[Any, int]:
    """Builds an O(1) node-to-component mapping for fast reachability checks."""
    component_map = {}
    if nx.is_directed(G):
        components = nx.strongly_connected_components(G)
    else:
        components = nx.connected_components(G)

    for comp_id, comp_nodes in enumerate(components):
        for node in comp_nodes:
            component_map[node] = comp_id
            
    return component_map


#--------------------

# Core routing engine

#-------------------- 

def find_max_scenic_path_constrained_v4(
    G: nx.Graph,
    start_node: Any,
    target_node: Any,
    max_time_seconds: float,
    walking_speed: float = 1.25,
    component_map: Optional[Dict[Any, int]] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Finds the path from start_node to target_node maximizing total scenic score
    while staying strictly within max_time_seconds. Features O(1) heap memory pointers,
    adaptive Pareto pruning, exact Haversine distance, and component reachability checks.
    """
    if verbose:
        print("\n" + "=" * 60)
        print(" [ROUTING ENGINE v4] Initializing Fully Hardened Scenic Route Search")
        print(f"   • Start Node: {start_node} | Target Node: {target_node}")
        print(f"   • Time Budget: {max_time_seconds}s ({round(max_time_seconds / 60.0, 1)} mins)")
        print("=" * 60)

    # validating existence
    if start_node not in G:
        return {"status": "error", "message": f"Start node {start_node} missing from graph."}
    if target_node not in G:
        return {"status": "error", "message": f"Target node {target_node} missing from graph."}

    # 2. O(1) connectivity pre-screening
    if component_map is not None:
        start_comp = component_map.get(start_node)
        target_comp = component_map.get(target_node)
        if start_comp is None or target_comp is None or start_comp != target_comp:
            return {
                "status": "unreachable_target",
                "message": "Start and target nodes exist in disconnected network subgraphs.",
            }

    # Dynamic Pareto bucket sizing based on overall time budget
    adaptive_bucket_size = max(2.0, min(10.0, max_time_seconds / 120.0))

    # predecessor dictionary: state_id -> (parent_state_id, node_id)
    state_counter = 0
    predecessors: Dict[int, Tuple[Optional[int], Any]] = {state_counter: (None, start_node)}

    # priority queue tuple:
    # (-total_scenic_score, elapsed_time, current_node, state_id, prev_heading, visited_landmarks, visited_nodes)
    # FIX: Added frozenset({start_node}) as 7th item to track visited nodes per branch
    pq = [(-0.0, 0.0, start_node, state_counter, None, frozenset(), frozenset({start_node}))]

    # Pareto records: node -> {time_bucket: best_scenic_score}
    pareto_records: Dict[Any, Dict[int, float]] = {node: {} for node in G.nodes}

    best_solution = None
    best_max_score = -1.0
    best_target_state_id = None

    iterations = 0
    pruned_by_heuristic = 0
    pruned_by_pareto = 0

    while pq:
        iterations += 1
        (
            neg_score,
            elapsed_time,
            current_node,
            state_id,
            prev_heading,
            visited_landmarks,
            visited_nodes,  # FIX: Extracted branch visited nodes
        ) = heapq.heappop(pq)
        current_score = -neg_score

        # target reached check
        if current_node == target_node:
            if current_score > best_max_score:
                best_max_score = current_score
                best_target_state_id = state_id
                best_solution = {
                    "status": "success",
                    "total_time_min": round(elapsed_time / 60.0, 2),
                    "total_scenic_score": round(current_score, 2),
                }
                if verbose:
                    print(f" [TARGET REACHED] Score: {round(current_score, 2)} | Time: {round(elapsed_time / 60.0, 2)}m")
            continue

        # adaptive Pareto dominance check
        time_bucket = int(elapsed_time // adaptive_bucket_size)
        node_buckets = pareto_records[current_node]

        if time_bucket in node_buckets and node_buckets[time_bucket] >= current_score:
            pruned_by_pareto += 1
            continue

        node_buckets[time_bucket] = current_score

        # exploring outgoing neighbors
        for neighbor in G.neighbors(current_node):
            # FIX: Prevent backtracking or ping-ponging back to ANY node already in this branch's history
            if neighbor in visited_nodes:
                continue

            raw_edge = G.get_edge_data(current_node, neighbor)
            attr = extract_best_edge_attributes(raw_edge)

            length = float(attr.get("length", 1.0))
            raw_scenic = float(attr.get("scenic_score", 0.0))
            associated_landmark = _normalize_landmark_id(attr.get("landmark_id", None))

            # turn penalty
            current_heading = calculate_heading(G.nodes[current_node], G.nodes[neighbor])
            turn_penalty_seconds = 0.0
            if prev_heading is not None:
                angle_change = calculate_turn_angle(prev_heading, current_heading)
                if angle_change > 80:
                    turn_penalty_seconds = (angle_change / 180.0) * 10.0

            edge_time = (length / walking_speed) + turn_penalty_seconds
            new_elapsed_time = elapsed_time + edge_time

            # heuristic budget pruning
            min_remaining_time = network_bounded_heuristic(
                neighbor, target_node, G, walking_speed
            )
            if new_elapsed_time + min_remaining_time > max_time_seconds:
                pruned_by_heuristic += 1
                continue

            # landmark saturation decay
            new_visited_landmarks = visited_landmarks
            scenic_multiplier = 1.0

            if associated_landmark is not None:
                times_seen = sum(1 for item in visited_landmarks if item == associated_landmark)
                scenic_multiplier = 0.5 ** times_seen
                new_visited_landmarks = visited_landmarks | {associated_landmark}

            effective_scenic = raw_scenic * scenic_multiplier
            new_score = current_score + effective_scenic

            # registering new state pointer
            state_counter += 1
            predecessors[state_counter] = (state_id, neighbor)

            heapq.heappush(
                pq,
                (
                    -new_score,
                    new_elapsed_time,
                    neighbor,
                    state_counter,
                    current_heading,
                    new_visited_landmarks,
                    visited_nodes | {neighbor},  # FIX: Pass forward updated node history
                ),
            )

    # path reconstruction
    if best_solution is not None and best_target_state_id is not None:
        reconstructed_path = []
        curr_state: Optional[int] = best_target_state_id
        while curr_state is not None:
            parent_state, node_id = predecessors[curr_state]
            reconstructed_path.append(node_id)
            curr_state = parent_state

        reconstructed_path.reverse()
        best_solution["path"] = reconstructed_path
        best_solution["total_nodes_visited"] = len(reconstructed_path)

    if verbose:
        print("\n📊 [DIAGNOSTIC SUMMARY]")
        print(f"   • Total Iterations Evaluated: {iterations}")
        print(f"   • Branches Pruned (Time Exceeded): {pruned_by_heuristic}")
        print(f"   • Branches Pruned (Suboptimal Pareto State): {pruned_by_pareto}")
        print("=" * 60 + "\n")

    if best_solution is None:
        return {
            "status": "no_path_found",
            "message": f"No path found within the {round(max_time_seconds / 60.0, 1)} minute time limit.",
        }

    return best_solution

def get_route_from_coords(
    G: nx.Graph,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    max_time_seconds: float = 1800.0,
    mode: str = "scenic",
    component_map: Optional[Dict[Any, int]] = None,
) -> Dict[str, Any]:
    import osmnx as ox
    import networkx as nx

    # 1. Ensure coordinate lookup happens on unprojected WGS84 degree graph
    # If G is in EPSG:32632, unproject it to EPSG:4326 for node snapping & Lat/Lon output
    if G.graph.get("crs") != "EPSG:4326":
        G_deg = ox.project_graph(G, to_crs="EPSG:4326")
    else:
        G_deg = G

    # 2. Snap Lat/Lon coordinates to nearest OSMnx nodes (X=lon, Y=lat)
    start_node = ox.distance.nearest_nodes(G_deg, X=start_lon, Y=start_lat)
    target_node = ox.distance.nearest_nodes(G_deg, X=end_lon, Y=end_lat)

    if start_node == target_node:
        return {
            "status": "error",
            "message": "Start and target snapped to the exact same node. Pick points further apart.",
        }

    WALKING_SPEED_MPS = 1.25

    # 3. Pathfinding mode execution
    if mode == "shortest":
        try:
            path_nodes = nx.shortest_path(
                G, start_node, target_node, weight="length"
            )
            status = "success"
        except nx.NetworkXNoPath:
            return {"status": "no_path_found", "message": "No path exists."}
    else:
        # PERFORMANCE OPTIMIZATION: Compute shortest distance first to dynamically budget scenic search time
        try:
            shortest_nodes = nx.shortest_path(G, start_node, target_node, weight="length")
            shortest_length = sum(
                float(G[shortest_nodes[i]][shortest_nodes[i+1]][0].get("length", 0.0))
                for i in range(len(shortest_nodes) - 1)
            )
            shortest_time = shortest_length / WALKING_SPEED_MPS
            # Allow scenic route up to 30% longer than shortest path
            dynamic_budget = max(shortest_time * 1.30, 300.0)
        except nx.NetworkXNoPath:
            dynamic_budget = max_time_seconds

        res = find_max_scenic_path_constrained_v4(
            G=G,
            start_node=start_node,
            target_node=target_node,
            max_time_seconds=dynamic_budget,
            walking_speed=WALKING_SPEED_MPS,
            component_map=component_map,
            verbose=False,
        )
        if res.get("status") != "success":
            return res
        path_nodes = res["path"]
        status = res["status"]

    # 4. Extract degrees (lat, lon) coordinates for Leaflet
    # Remove consecutive duplicate nodes or micro-backtracking
    clean_path_nodes = []
    for node in path_nodes:
        if not clean_path_nodes or node != clean_path_nodes[-1]:
            clean_path_nodes.append(node)

    route_coords = []
    total_distance_meters = 0.0

    for i in range(len(clean_path_nodes)):
        node = clean_path_nodes[i]
        node_data = G_deg.nodes[node]
        route_coords.append((float(node_data["y"]), float(node_data["x"])))

        # Accumulate exact road segment distances
        if i < len(clean_path_nodes) - 1:
            next_node = clean_path_nodes[i+1]
            edge_data = G[node][next_node][0]
            total_distance_meters += float(edge_data.get("length", 0.0))

    # Calculate metrics at 4.5 km/h (1.25 m/s)
    total_distance_km = round(total_distance_meters / 1000.0, 2)
    total_time_min = round((total_distance_meters / WALKING_SPEED_MPS) / 60.0, 1)

    return {
        "status": status,
        "mode": mode,
        "coordinates": route_coords,
        "total_nodes": len(clean_path_nodes),
        "distance_km": total_distance_km,
        "time_min": total_time_min,
        "walking_speed_kmh": 4.5,
    }
import random

def generate_scenic_loops(
    G: nx.Graph,
    start_lat: float,
    start_lon: float,
    max_time_minutes: float,
    walking_speed_mps: float = 1.25,
    component_map: Optional[Dict[Any, int]] = None,
) -> Dict[str, Any]:
  import networkx as nx
  import osmnx as ox

  if G.graph.get("crs") != "EPSG:4326":
    G_deg = ox.project_graph(G, to_crs="EPSG:4326")
  else:
    G_deg = G

  start_node = ox.distance.nearest_nodes(G_deg, X=start_lon, Y=start_lat)
  max_time_seconds = float(max_time_minutes) * 60.0
  outbound_budget = max_time_seconds * 0.45

  # 1. Dijkstra radius search up to outbound budget
  lengths, _ = nx.single_source_dijkstra(
      G, start_node, cutoff=outbound_budget, weight="length"
  )

  # 2. Pick candidate pivots away from origin
  candidates = []
  for node, dist in lengths.items():
    if node == start_node or dist < 250:  # Enforce minimum distance
      continue
    scenic_sum = sum(
        float(G[node][nbr][0].get("scenic_score", 0.0))
        for nbr in G.neighbors(node)
    )
    candidates.append((scenic_sum, node))

  candidates.sort(key=lambda x: x[0], reverse=True)
  if not candidates:
    return {
        "status": "no_path_found",
        "message": "Time limit too short for a non-overlapping loop.",
    }

  # 3. Outbound search
  _, pivot_node = candidates[0]
  outbound_res = find_max_scenic_path_constrained_v4(
      G=G,
      start_node=start_node,
      target_node=pivot_node,
      max_time_seconds=outbound_budget,
      walking_speed=walking_speed_mps,
      component_map=component_map,
      verbose=False,
  )

  if outbound_res.get("status") != "success":
    return {
        "status": "no_path_found",
        "message": "Could not compute outbound leg.",
    }

  out_path = outbound_res["path"]

  # 4. TEMPORARILY PENALIZE OUTBOUND EDGES TO PREVENT OVERLAP
  # Copy graph temporarily so we don't mutate global state
  G_loop = G.copy()
  outbound_edges = set()
  for i in range(len(out_path) - 1):
    u, v = out_path[i], out_path[i + 1]
    outbound_edges.add((u, v))
    outbound_edges.add((v, u))
    if G_loop.has_edge(u, v):
      # Inflate length penalty on outbound edges to force return on parallel streets
      for key in G_loop[u][v]:
        G_loop[u][v][key]["length"] = (
            float(G_loop[u][v][key].get("length", 10.0)) * 10.0
        )
        G_loop[u][v][key]["scenic_score"] = 0.0

  # 5. Return search on modified graph
  return_res = find_max_scenic_path_constrained_v4(
      G=G_loop,
      start_node=pivot_node,
      target_node=start_node,
      max_time_seconds=max_time_seconds * 0.55,
      walking_speed=walking_speed_mps,
      component_map=component_map,
      verbose=False,
  )

  if return_res.get("status") != "success":
    # Fallback to shortest return path if constrained search gets trapped
    try:
      ret_path = nx.shortest_path(
          G_loop, pivot_node, start_node, weight="length"
      )
    except nx.NetworkXNoPath:
      return {
          "status": "no_path_found",
          "message": "Could not form a non-overlapping return path.",
      }
  else:
    ret_path = return_res["path"]

  # Merge paths seamlessly
  full_path = out_path + ret_path[1:]

  # Compute metrics
  total_dist_m = sum(
      float(G[full_path[i]][full_path[i + 1]][0].get("length", 0.0))
      for i in range(len(full_path) - 1)
      if G.has_edge(full_path[i], full_path[i + 1])
  )

  route_coords = [
      (float(G_deg.nodes[n]["y"]), float(G_deg.nodes[n]["x"]))
      for n in full_path
  ]

  return {
      "status": "success",
      "mode": "scenic_loop",
      "loops": [{
          "coordinates": route_coords,
          "total_nodes": len(full_path),
          "distance_km": round(total_dist_m / 1000.0, 2),
          "time_min": round((total_dist_m / walking_speed_mps) / 60.0, 1),
      }],
  }

def generate_random_scenic_walk(
    G: nx.Graph,
    start_lat: float,
    start_lon: float,
    max_time_minutes: float,
    walking_speed_mps: float = 1.25,
    component_map: Optional[Dict[Any, int]] = None,
) -> Dict[str, Any]:
    """Generates a random one-way scenic walk terminating at a scenic target node."""
    import networkx as nx
    import osmnx as ox

    if G.graph.get("crs") != "EPSG:4326":
        G_deg = ox.project_graph(G, to_crs="EPSG:4326")
    else:
        G_deg = G

    start_node = ox.distance.nearest_nodes(G_deg, X=start_lon, Y=start_lat)
    max_time_seconds = float(max_time_minutes) * 60.0

    # 1. Find nodes reachable near target walk duration (between 70% and 100% of max time)
    min_dist_m = max_time_seconds * walking_speed_mps * 0.70
    max_dist_m = max_time_seconds * walking_speed_mps

    lengths, _ = nx.single_source_dijkstra(G, start_node, cutoff=max_dist_m, weight="length")

    candidate_targets = [
        node for node, dist in lengths.items()
        if min_dist_m <= dist <= max_dist_m
    ]

    if not candidate_targets:
        # Fallback to furthest reachable node
        candidate_targets = sorted(lengths.keys(), key=lambda n: lengths[n], reverse=True)[:10]

    # 2. Select a random target node from the top 10 scenic candidates in range
    candidate_scores = []
    for n in candidate_targets:
        scenic_score = sum(float(G[n][nbr][0].get("scenic_score", 0.0)) for nbr in G.neighbors(n))
        candidate_scores.append((scenic_score, n))
    
    candidate_scores.sort(key=lambda x: x[0], reverse=True)
    top_candidates = candidate_scores[:10]
    
    _, target_node = random.choice(top_candidates)

    # 3. Compute scenic path to selected random target
    res = find_max_scenic_path_constrained_v4(
        G=G, start_node=start_node, target_node=target_node,
        max_time_seconds=max_time_seconds, walking_speed=walking_speed_mps,
        component_map=component_map, verbose=False
    )

    if res.get("status") != "success":
        return res

    path_nodes = res["path"]
    total_dist_m = sum(
        float(G[path_nodes[i]][path_nodes[i+1]][0].get("length", 0.0))
        for i in range(len(path_nodes) - 1)
    )

    route_coords = [(float(G_deg.nodes[n]["y"]), float(G_deg.nodes[n]["x"])) for n in path_nodes]

    return {
        "status": "success",
        "mode": "random_scenic_walk",
        "coordinates": route_coords,
        "total_nodes": len(path_nodes),
        "distance_km": round(total_dist_m / 1000.0, 2),
        "time_min": round((total_dist_m / walking_speed_mps) / 60.0, 1)
    }
# Dummy graph for testing purposes

if __name__ == "__main__":
    import networkx as nx

    
    G_test = nx.DiGraph()
    G_test.add_node(1, x=7.6857, y=45.0709)  # Palazzo Madama
    G_test.add_node(2, x=7.6860, y=45.0694)  # Galleria Subalpina
    G_test.add_node(3, x=7.6931, y=45.0689)  # Mole Antonelliana

    G_test.add_edge(1, 2, length=200.0, scenic_score=4.8, landmark_id="1")
    G_test.add_edge(2, 3, length=500.0, scenic_score=5.0, landmark_id="2")

    result = find_max_scenic_path_constrained_v4(
        G=G_test,
        start_node=1,
        target_node=3,
        max_time_seconds=1500,  # slightly large time budget
        verbose=True
    )

    print("\nRESULT:", result)