from flask import Flask, jsonify, request
from flask_cors import CORS
import osmnx as ox
from routing_engine import build_component_map, get_route_from_coords, generate_scenic_loops, generate_random_scenic_walk

app = Flask(__name__)
CORS(app)

GRAPH_PATH = "data/turin_scenic_scored.graphml"

print("📦 Loading pre-scored graph from disk...")
G = ox.load_graphml(GRAPH_PATH)
component_map = build_component_map(G)
print("🚀 Server ready!")


@app.route("/api/route", methods=["GET"])
def compute_route():
    try:
        start_lat = float(request.args.get("start_lat"))
        start_lon = float(request.args.get("start_lon"))
        end_lat = float(request.args.get("end_lat"))
        end_lon = float(request.args.get("end_lon"))
        mode = request.args.get("mode", "scenic")
        max_time = float(request.args.get("max_time_seconds", 1800.0))

        result = get_route_from_coords(
            G=G,
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            max_time_seconds=max_time,
            mode=mode,
            component_map=component_map,
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/api/scenic-loop", methods=["GET"])
def get_scenic_loop():
    start_lat = float(request.args.get("lat"))
    start_lon = float(request.args.get("lon"))
    max_time_min = float(request.args.get("max_time", 30))

    result = generate_scenic_loops(
        G=G,
        start_lat=start_lat,
        start_lon=start_lon,
        max_time_minutes=max_time_min,
        component_map=component_map,
    )
    return jsonify(result)
@app.route('/api/random-scenic-walk', methods=['GET'])
def get_random_scenic_walk():
    try:
        start_lat = float(request.args.get('lat'))
        start_lon = float(request.args.get('lon'))
        max_time_min = float(request.args.get('max_time', 30))

        result = generate_random_scenic_walk(
            G=G,
            start_lat=start_lat,
            start_lon=start_lon,
            max_time_minutes=max_time_min,
            component_map=component_map
        )
        return jsonify(result)
    except Exception as e:
        print(f"Error in /api/random-scenic-walk: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)