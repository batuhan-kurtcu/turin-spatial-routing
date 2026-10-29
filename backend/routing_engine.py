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

    # validating the existance
    if start_node not in G:
        return {"status": "error", "message": f"Start node {start_node} missing from graph."}
    if target_node not in G:
        return {"status": "error", "message": f"Target node {target_node} missing from graph."}

    # 2. O(1) connectivity pre-screening so that we know if a route is even possible
    if component_map is not None:
        start_comp = component_map.get(start_node)
        target_comp = component_map.get(target_node)
        if start_comp is None or target_comp is None or start_comp != target_comp:
            return {
                "status": "unreachable_target",
                "message": f"Start and target nodes exist in disconnected network subgraphs.",
            }

    # Dynamic Pareto bucket sizing based on overall time budget/limit or whatever you would like to call
    adaptive_bucket_size = max(2.0, min(10.0, max_time_seconds / 120.0))

    # predecessor dictionary: state_id -> (parent_state_id, node_id)
    state_counter = 0
    predecessors: Dict[int, Tuple[Optional[int], Any]] = {state_counter: (None, start_node)}

    # priority queue tuple:
    # (-total_scenic_score, elapsed_time, current_node, state_id, prev_heading, visited_landmarks)
    pq = [(-0.0, 0.0, start_node, state_counter, None, frozenset())]

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
            raw_edge = G.get_edge_data(current_node, neighbor)
            attr = extract_best_edge_attributes(raw_edge)

            length = float(attr.get("length", 1.0))
            raw_scenic = float(attr.get("scenic_score", 0.0))
            associated_landmark = _normalize_landmark_id(attr.get("landmark_id", None))

            # turn penalty to maximize the actual exploration
            current_heading = calculate_heading(G.nodes[current_node], G.nodes[neighbor])
            turn_penalty_seconds = 0.0
            if prev_heading is not None:
                angle_change = calculate_turn_angle(prev_heading, current_heading)
                if angle_change > 80:
                    turn_penalty_seconds = (angle_change / 180.0) * 8.0

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