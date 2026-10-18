"""
UNPAM Smart Campus Navigation System
Algorithm Design and Analysis - Project

Run:
    pip install -r requirements.txt
    python app.py                # http://127.0.0.1:5000
    python app.py --selftest     # quick algorithm check, no server
"""
import random
import statistics
import sys

from flask import Flask, jsonify, render_template, request

from campus_data import SELECTABLE_KINDS, build_campus, to_adjacency
from dijkstra import dijkstra

app = Flask(__name__)
app.json.sort_keys = False

WALK_SPEED = 1.3                         # m/s used to estimate walking time
BLOCKED_WHEN_ACCESSIBLE = frozenset({"stairs", "escalator"})

# --------------------------------------------------------------------------- #
# The graph is built once at start-up
# --------------------------------------------------------------------------- #
CAMPUS = build_campus()
ROOMS = CAMPUS.rooms                           # drawable / searchable places
POS = CAMPUS.pos                               # every node -> [x, z, level, floor, building]
GRAPH = to_adjacency(CAMPUS.edges)             # adjacency list  O(V + E) space
SELECTABLE = [r["id"] for r in ROOMS.values() if r["k"] in SELECTABLE_KINDS]


# --------------------------------------------------------------------------- #
# Turn a raw path into human-readable steps
# --------------------------------------------------------------------------- #
def _name(nid):
    r = ROOMS[nid]
    return r["label"] + (f" ({r['desc']})" if r["desc"] and not r["desc"].startswith("Room") else "")


def _place(nid):
    p = POS[nid]
    return "Outdoors" if p[4] == "Campus" else f"Gedung {p[4]} - floor {p[3]}"


def _mode(t):
    return t if t in ("lift", "stairs", "escalator", "outdoor") else "walk"


def build_steps(path, legs):
    """Merge consecutive legs of the same movement mode into one instruction."""
    steps = [{"icon": "fa-location-dot", "mode": "start", "title": f"Start at {_name(path[0])}",
              "detail": _place(path[0]), "dist": 0, "from": 0, "to": 0, "pass": []}]
    i = 0
    while i < len(legs):
        mode, j, total = _mode(legs[i][3]), i, 0.0
        while j < len(legs) and _mode(legs[j][3]) == mode:
            total += legs[j][2]
            j += 1
        start_id, end_id = legs[i][0], legs[j - 1][1]
        if mode in ("lift", "stairs", "escalator"):
            f1, f2 = POS[start_id][3], POS[end_id][3]
            how = {"lift": "Take the lift", "stairs": "Take the stairs", "escalator": "Take the escalator"}[mode]
            steps.append({"icon": "fa-elevator" if mode == "lift" else "fa-stairs", "mode": mode,
                          "title": f"{how} {'up' if f2 > f1 else 'down'} from floor {f1} to floor {f2}",
                          "detail": f"Gedung {POS[start_id][4]}", "dist": round(total, 1),
                          "from": i, "to": j, "pass": []})
        else:
            seen = []
            for nid in path[i + 1:j]:            # rooms whose door is on this stretch of corridor
                for rid in CAMPUS.doors.get(nid, []):
                    if rid not in (path[0], path[-1]) and rid not in seen and ROOMS[rid]["k"] != "service":
                        seen.append(rid)
            verb = "Walk outside" if mode == "outdoor" else "Walk"
            steps.append({"icon": "fa-person-walking", "mode": mode,
                          "title": f"{verb} {round(total)} m to {_name(end_id)}",
                          "detail": _place(end_id), "dist": round(total, 1), "from": i, "to": j,
                          "pass": [ROOMS[r]["label"] for r in seen[:6]]})
        i = j
    steps.append({"icon": "fa-flag-checkered", "mode": "end", "title": f"Arrive at {_name(path[-1])}",
                  "detail": _place(path[-1]), "dist": 0, "from": len(path) - 1, "to": len(path) - 1, "pass": []})
    return steps


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/init_data")
def init_data():
    """Places + building metadata for the 3D viewer."""
    return jsonify({
        "nodes": list(ROOMS.values()),
        "meta": CAMPUS.meta,
        "stats": {"V": len(GRAPH), "E": len(CAMPUS.edges), "places": len(ROOMS)},
    })


@app.route("/api/find_path", methods=["GET", "POST"])
def find_path():
    data = request.get_json(silent=True) or request.values
    start, end = data.get("start"), data.get("end")
    accessible = str(data.get("accessible", "false")).lower() in ("1", "true", "yes", "on")

    if start not in ROOMS or end not in ROOMS or start not in GRAPH or end not in GRAPH:
        return jsonify({"found": False, "message": "Unknown start or destination."}), 400
    if start == end:
        return jsonify({"found": False, "message": "Start and destination are the same place."}), 400

    res = dijkstra(GRAPH, start, end, BLOCKED_WHEN_ACCESSIBLE if accessible else frozenset())
    if not res["found"]:
        return jsonify({"found": False, "accessible": accessible, "stats": res["stats"],
                        "message": "No route found" + (" without using stairs or escalators." if accessible else ".")})

    floors = []
    for nid in res["path"]:
        p = POS[nid]
        if p[4] != "Campus" and {"b": p[4], "f": p[3]} not in floors:
            floors.append({"b": p[4], "f": p[3]})

    return jsonify({
        "found": True, "accessible": accessible,
        "path": res["path"], "coords": [POS[n] for n in res["path"]],
        "distance": round(res["distance"], 1), "time_s": round(res["distance"] / WALK_SPEED),
        "steps": build_steps(res["path"], res["legs"]),
        "floors": floors, "stats": res["stats"],
    })


@app.route("/api/benchmark")
def benchmark():
    """Empirical analysis: campus queries + synthetic scaling test."""
    runs = max(10, min(int(request.args.get("runs", 200)), 1000))
    accessible = request.args.get("accessible", "false") == "true"
    blocked = BLOCKED_WHEN_ACCESSIBLE if accessible else frozenset()
    rnd = random.Random(42)

    times, popped = [], []
    for _ in range(runs):
        a, b = rnd.sample(SELECTABLE, 2)
        r = dijkstra(GRAPH, a, b, blocked)
        times.append(r["stats"]["elapsed_ms"])
        popped.append(r["stats"]["nodes_popped"])

    scaling = []
    for v in (1000, 2000, 4000, 8000, 16000):
        g = _random_sparse_graph(v, rnd)
        ts = [dijkstra(g, 0, v - 1)["stats"]["elapsed_ms"] for _ in range(5)]
        scaling.append({"V": v, "E": sum(len(x) for x in g.values()) // 2, "avg_ms": round(statistics.mean(ts), 3)})

    return jsonify({
        "campus": {"V": len(GRAPH), "E": len(CAMPUS.edges), "queries": runs, "accessible": accessible,
                   "avg_ms": round(statistics.mean(times), 3), "max_ms": round(max(times), 3),
                   "min_ms": round(min(times), 3), "avg_nodes_popped": round(statistics.mean(popped), 1)},
        "scaling": scaling,
    })


def _random_sparse_graph(v, rnd):
    """Connected sparse graph with ~2V edges, used only for the scaling benchmark."""
    g = {i: [] for i in range(v)}
    for i in range(1, v):
        j = rnd.randrange(0, i)
        w = rnd.uniform(1, 20)
        g[i].append((j, w, "walk"))
        g[j].append((i, w, "walk"))
    for _ in range(v):
        a, b = rnd.randrange(v), rnd.randrange(v)
        if a != b:
            w = rnd.uniform(1, 20)
            g[a].append((b, w, "walk"))
            g[b].append((a, w, "walk"))
    return g


# --------------------------------------------------------------------------- #
def selftest():
    print(f"Graph: V={len(GRAPH)}  E={len(CAMPUS.edges)}  places={len(ROOMS)}")
    tests = [("GATE", "C8-LABPEMROGRAMAN5"), ("GATE", "B9-V932"), ("A1-V101", "A6-V631")]
    for s, e in tests:
        for acc in (False, True):
            r = dijkstra(GRAPH, s, e, BLOCKED_WHEN_ACCESSIBLE if acc else frozenset())
            types = {leg[3] for leg in r["legs"]}
            print(f"{s:>8} -> {e:<22} accessible={acc!s:<5} found={r['found']} dist={r['distance']:.1f} m  "
                  f"vertical={sorted(types & {'lift', 'stairs', 'escalator'})}  {r['stats']}")
            if acc:
                assert not (types & BLOCKED_WHEN_ACCESSIBLE), "accessible route used stairs/escalator!"
    print("Self-test passed.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        app.run(host="127.0.0.1", port=5000, debug=True)
