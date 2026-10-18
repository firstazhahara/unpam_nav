"""
campus_data.py
--------------
Builds the UNPAM (Viktor Campus) weighted graph  G = (V, E)  from plans.json,
which holds the room boxes copied from the PDF "Denah Ruangan Gedung A,B,C".

LAYOUT = THE PDF
    Every room keeps the position, width and height it has on its PDF page.
    The PDF has no scale, so sizes are ESTIMATED with one factor per plan type:

        S_MAIN = 0.10 m per PDF point  -> a classroom box of 80 x 93 pt = 8.0 x 9.3 m
        S_WING = 0.07 m per PDF point  -> the rear "Belakang" plans are drawn larger on the page

    Change the two constants below to re-scale everything.

WHAT IS GENERATED (the PDF shows rooms only, no corridors)
    * Corridors: the empty space between rooms is turned into a 2 m walking grid.
      Each grid cell is a graph node; neighbouring cells are joined by edges
      (weight = metres).  Cells farther than WALK_RADIUS from any room are dropped.
    * Doors: every room is joined to its nearest walkable cell.
    * Lifts / stairs / escalators on consecutive floors are linked into vertical
      "shafts" by position; their travel cost is in metre-equivalents.
    * Floors without a PDF plan (B1 and C1) and the lobbies / outdoor walkway
      from the Main Gate are ASSUMPTIONS.

Edge types:  walk | outdoor | lift | stairs | escalator
"""
import json
import os
import re
from collections import deque
from math import ceil, floor, hypot, sqrt

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- #
# Tunable constants
# --------------------------------------------------------------------------- #
S_MAIN = 0.10          # metres per PDF point, main plans
S_WING = 0.07          # metres per PDF point, rear ("Belakang") plans
GRID = 2.0             # walking-grid cell size (m)
WALK_RADIUS = 9.0      # keep only cells within this distance of a room (m)
WING_GAP = 8.0         # gap between the main block and the rear wing (m)
BUILDING_GAP = 18.0    # gap between buildings along the campus (m)
WALKWAY_X = -16.0      # outdoor walkway (m)
NODE_STEP = 4.0        # spacing of outdoor nodes (m)

LIFT_BOARDING = 8.0    # waiting cost for a lift, added at each end (metre-equivalent)
LIFT_PER_FLOOR = 3.0
STAIRS_PER_FLOOR = 10.0
ESC_PER_FLOOR = 6.0
MATCH_RADIUS = 50.0    # max distance to link a lift/stair on one floor to the shaft below (m)

ASSUMED_GROUND = {"B", "C"}      # buildings whose floor 1 has no plan in the PDF
SKYBRIDGES = []                  # [(buildingX, buildingY, floor)] - none known

BUILDINGS = {
    "A": {"name": "Gedung A", "color": "#2f6fb7"},
    "B": {"name": "Gedung B", "color": "#1f8a70"},
    "C": {"name": "Gedung C", "color": "#8a4fb5"},
}

KIND_META = {
    "classroom": {"name": "Classroom", "color": "#4f8fd6"},
    "lab": {"name": "Laboratory", "color": "#8e5bbf"},
    "office": {"name": "Office / Faculty", "color": "#e58a2b"},
    "toilet": {"name": "Toilet", "color": "#7b8794"},
    "prayer": {"name": "Musholla", "color": "#2e9e6b"},
    "service": {"name": "Storage / Service", "color": "#a39482"},
    "lobby": {"name": "Lobby", "color": "#c7162b"},
    "gate": {"name": "Main Gate", "color": "#c7162b"},
    "lift": {"name": "Lift", "color": "#0066cc"},
    "stairs": {"name": "Stairs", "color": "#f99b11"},
    "escalator": {"name": "Escalator", "color": "#d4a017"},
    "void": {"name": "Unlabelled space", "color": "#9aa4af"},
}
VERTICAL = {"lift": LIFT_PER_FLOOR, "stairs": STAIRS_PER_FLOOR, "escalator": ESC_PER_FLOOR}
VERTICAL_NAME = {"lift": "Lift", "stairs": "Stairs", "escalator": "Escalator"}
SELECTABLE_KINDS = {"classroom", "lab", "office", "toilet", "prayer", "service", "lobby", "gate"}


def _slug(text):
    return re.sub(r"[^A-Z0-9]+", "", text.upper()) or "ROOM"


# --------------------------------------------------------------------------- #
# Step 1 - read plans.json and convert PDF points to metres
# --------------------------------------------------------------------------- #
def _load_building_floors(b):
    """-> {floor: {"main": [rect...], "wing": [rect...], "plan": True}}  (building-local metres)"""
    with open(os.path.join(HERE, "plans.json"), encoding="utf-8") as fh:
        pages = json.load(fh)
    floors = {}
    for pg in pages:
        if pg["building"] != b:
            continue
        rooms = pg["rooms"]
        minx = min(r["x0"] for r in rooms)
        miny = min(r["y0"] for r in rooms)
        s = S_MAIN if pg["part"] == "main" else S_WING
        rects = [{"label": r["label"], "desc": r["desc"], "kind": r["kind"],
                  "x0": (r["x0"] - minx) * s, "z0": (r["y0"] - miny) * s,
                  "x1": (r["x1"] - minx) * s, "z1": (r["y1"] - miny) * s} for r in rooms]
        fl = floors.setdefault(pg["floor"], {"main": [], "wing": [], "plan": True})
        fl[pg["part"]] = rects
    return floors


def _bbox(rects):
    return (min(r["x0"] for r in rects), min(r["z0"] for r in rects),
            max(r["x1"] for r in rects), max(r["z1"] for r in rects))


# --------------------------------------------------------------------------- #
# Step 2 - corridors: free space between the rooms, as a walking grid
# --------------------------------------------------------------------------- #
def _free_cells(rects, region, free_all=False):
    """Return set of (i, j) grid cells that are walkable inside `region`."""
    x0, z0, x1, z1 = region
    i0, i1 = floor(x0 / GRID), ceil(x1 / GRID)
    j0, j1 = floor(z0 / GRID), ceil(z1 / GRID)
    ii, jj = np.meshgrid(np.arange(i0, i1), np.arange(j0, j1), indexing="ij")
    cx, cz = (ii + 0.5) * GRID, (jj + 0.5) * GRID
    ok = (cx >= x0) & (cx <= x1) & (cz >= z0) & (cz <= z1)
    near = np.zeros_like(ok) if not free_all else np.ones_like(ok)
    for r in rects:
        inside = (cx > r["x0"] - 0.2) & (cx < r["x1"] + 0.2) & (cz > r["z0"] - 0.2) & (cz < r["z1"] + 0.2)
        ok &= ~inside
        if not free_all:
            dx = np.maximum(np.maximum(r["x0"] - cx, cx - r["x1"]), 0)
            dz = np.maximum(np.maximum(r["z0"] - cz, cz - r["z1"]), 0)
            near |= np.hypot(dx, dz) <= WALK_RADIUS
    ok &= near
    cells = {(int(a), int(b)) for a, b in zip(ii[ok], jj[ok])}
    return _largest_component(cells)


def _largest_component(cells):
    seen, best = set(), set()
    for c in cells:
        if c in seen:
            continue
        comp, q = {c}, deque([c])
        seen.add(c)
        while q:
            i, j = q.popleft()
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (i + di, j + dj)
                if n in cells and n not in seen:
                    seen.add(n)
                    comp.add(n)
                    q.append(n)
        if len(comp) > len(best):
            best = comp
    return best


def _runs(cells):
    """Compress cells into horizontal runs [(i_start, i_end, j)] for the 3D floor tiles."""
    rows = {}
    for i, j in cells:
        rows.setdefault(j, []).append(i)
    out = []
    for j, lst in sorted(rows.items()):
        lst.sort()
        s = p = lst[0]
        for i in lst[1:]:
            if i != p + 1:
                out.append((s, p, j))
                s = i
            p = i
        out.append((s, p, j))
    return out


# --------------------------------------------------------------------------- #
# Step 3 - assemble everything
# --------------------------------------------------------------------------- #
class Campus:
    def __init__(self):
        self.rooms = {}        # id -> room dict (what the front end draws / searches)
        self.pos = {}          # every node id -> [x, z, level, floor, building]
        self.edges = []        # (a, b, weight, type)
        self.doors = {}        # walking-cell id -> [room ids that open onto it]
        self.meta = {}
        self.warnings = []

    def edge(self, a, b, w, t="walk"):
        self.edges.append((a, b, round(max(w, 0.5), 2), t))


def build_campus():
    C = Campus()
    meta_buildings = []
    oz = 0.0
    b_depth_end = {}
    lobbies = {}

    for b, binfo in BUILDINGS.items():
        floors = _load_building_floors(b)
        planned = sorted(floors)
        main_w = max(_bbox(fl["main"])[2] for fl in floors.values())
        main_d = max(_bbox(fl["main"])[3] for fl in floors.values())

        # ---- floors without a plan: copy lifts / stairs from the lowest planned floor
        if b in ASSUMED_GROUND:
            ref = floors[planned[0]]["main"]
            cores = [dict(r) for r in ref if r["kind"] in VERTICAL]
            floors[1] = {"main": cores, "wing": [], "plan": False, "region": _bbox(ref)}
        all_floors = sorted(floors)

        # ---- rear wing placement (same for every floor of the building)
        for f in planned:
            fl = floors[f]
            if fl["wing"]:
                wx0, wz0, wx1, wz1 = _bbox(fl["wing"])
                dx = (main_w - (wx1 - wx0)) / 2 - wx0
                dz = main_d + WING_GAP - wz0
                for r in fl["wing"]:
                    r["x0"] += dx; r["x1"] += dx; r["z0"] += dz; r["z1"] += dz

        # ---- per-floor grid + room specs
        specs = []             # room specs for this building (before naming)
        floor_cells = {}
        for lvl, f in enumerate(all_floors):
            fl = floors[f]
            plan = fl["plan"]
            main_region = fl.get("region") or _bbox(fl["main"])
            cells_main = _free_cells(fl["main"], main_region, free_all=not plan)
            cells_wing = set()
            wing_region = None
            if fl["wing"]:
                wing_region = _bbox(fl["wing"])
                cells_wing = _free_cells(fl["wing"], wing_region)
            floor_cells[f] = (cells_main, cells_wing)
            for part in ("main", "wing"):
                for r in fl[part]:
                    specs.append(dict(r, f=f, level=lvl, part=part, plan=plan))

        # ---- vertical shafts: link lifts / stairs / escalators between floors
        groups = {k: [] for k in VERTICAL}                  # kind -> [ {"last": spec, "members": [spec]} ]
        for f in all_floors:
            for kind in VERTICAL:
                cands = [s for s in specs if s["f"] == f and s["kind"] == kind]
                pairs = []
                for ci, s in enumerate(cands):
                    cx, cz = (s["x0"] + s["x1"]) / 2, (s["z0"] + s["z1"]) / 2
                    for gi, g in enumerate(groups[kind]):
                        lx, lz = (g["last"]["x0"] + g["last"]["x1"]) / 2, (g["last"]["z0"] + g["last"]["z1"]) / 2
                        d = hypot(cx - lx, cz - lz)
                        if d <= MATCH_RADIUS:
                            pairs.append((d, ci, gi))
                used_c, used_g = set(), set()
                for d, ci, gi in sorted(pairs):
                    if ci in used_c or gi in used_g:
                        continue
                    used_c.add(ci); used_g.add(gi)
                    groups[kind][gi]["members"].append(cands[ci])
                    groups[kind][gi]["last"] = cands[ci]
                for ci, s in enumerate(cands):
                    if ci not in used_c:
                        groups[kind].append({"last": s, "members": [s]})
        for kind, glist in groups.items():
            glist.sort(key=lambda g: (g["members"][0]["part"] == "wing", g["members"][0]["f"],
                                      g["members"][0]["z0"], g["members"][0]["x0"]))
            for n, g in enumerate(glist, 1):
                label = f"{VERTICAL_NAME[kind]} {b}" if len(glist) == 1 else f"{VERTICAL_NAME[kind]} {b}{n}"
                for s in g["members"]:
                    s["label"] = label + (" (rear wing)" if s["part"] == "wing" else "")
                    s["shaft"] = f"{kind}:{b}{n}"

        # ---- place the building in the world
        ox = 0.0
        # snap origin to the grid so cell centres line up with world coordinates
        oz = ceil(oz / GRID) * GRID
        wings = [_bbox(floors[f]["wing"]) for f in planned if floors[f]["wing"]]
        total_d = max([main_d] + [w[3] for w in wings])

        # ---- create nodes: rooms
        used_ids = {}
        node_of_spec = {}
        floor_room_ids = {f: [] for f in all_floors}
        for s in specs:
            base = f"{b}{s['f']}-{_slug(s['label'])}"
            used_ids[base] = used_ids.get(base, 0) + 1
            rid = base if used_ids[base] == 1 else f"{base}_{used_ids[base]}"
            w, d = s["x1"] - s["x0"], s["z1"] - s["z0"]
            room = {"id": rid, "label": s["label"], "desc": s["desc"], "b": b, "f": s["f"], "l": s["level"],
                    "k": s["kind"], "x": round(ox + s["x0"] + w / 2, 2), "z": round(oz + s["z0"] + d / 2, 2),
                    "w": round(w, 1), "d": round(d, 1), "plan": s["plan"]}
            if s["part"] == "wing":
                room["wing"] = True
            C.rooms[rid] = room
            C.pos[rid] = [room["x"], room["z"], s["level"], s["f"], b]
            node_of_spec[id(s)] = rid
            s["id"] = rid
            floor_room_ids[s["f"]].append(rid)

        # ---- walking-grid nodes + edges, doors
        floor_meta = []
        for lvl, f in enumerate(all_floors):
            cells_main, cells_wing = floor_cells[f]
            cell_id = {}
            for (i, j) in cells_main | cells_wing:
                cid = f"{b}{f}-c{i}_{j}"
                cell_id[(i, j)] = cid
                x, z = ox + (i + 0.5) * GRID, oz + (j + 0.5) * GRID
                C.pos[cid] = [round(x, 2), round(z, 2), lvl, f, b]
            for (i, j), cid in cell_id.items():
                for di, dj in ((1, 0), (0, 1), (1, 1), (1, -1)):
                    n = (i + di, j + dj)
                    if n not in cell_id:
                        continue
                    if di and dj and ((i + di, j) not in cell_id or (i, j + dj) not in cell_id):
                        continue          # no corner cutting
                    C.edge(cid, cell_id[n], GRID * (sqrt(2) if di and dj else 1))

            # bridge between main block and rear wing
            bridge_runs = []
            if cells_wing and cells_main:
                best = None
                wing_list = list(cells_wing)
                for (i, j) in cells_main:
                    for (k, m) in wing_list:
                        dd = (i - k) ** 2 + (j - m) ** 2
                        if best is None or dd < best[0]:
                            best = (dd, (i, j), (k, m))
                _, (i, j), (k, m) = best
                steps = max(abs(k - i), abs(m - j))
                prev = cell_id[(i, j)]
                for t in range(1, steps):
                    ci, cj = round(i + (k - i) * t / steps), round(j + (m - j) * t / steps)
                    if (ci, cj) in cell_id:
                        nid = cell_id[(ci, cj)]
                    else:
                        nid = f"{b}{f}-br{t}"
                        cell_id[(ci, cj)] = nid
                        C.pos[nid] = [round(ox + (ci + 0.5) * GRID, 2), round(oz + (cj + 0.5) * GRID, 2), lvl, f, b]
                        bridge_runs.append((ci, ci, cj))
                    C.edge(prev, nid, GRID * 1.5)
                    prev = nid
                C.edge(prev, cell_id[(k, m)], GRID * 1.5)

            # doors
            arr = np.array([[(i + 0.5) * GRID, (j + 0.5) * GRID] for (i, j) in cell_id.keys()])
            ids = list(cell_id.values())
            for s in [s for s in specs if s["f"] == f]:
                if s["kind"] == "void" or not len(arr):
                    continue
                dx = np.maximum(np.maximum(s["x0"] - arr[:, 0], arr[:, 0] - s["x1"]), 0)
                dz = np.maximum(np.maximum(s["z0"] - arr[:, 1], arr[:, 1] - s["z1"]), 0)
                dist_edge = np.hypot(dx, dz)
                cxm, czm = (s["x0"] + s["x1"]) / 2, (s["z0"] + s["z1"]) / 2
                dist_c = np.hypot(arr[:, 0] - cxm, arr[:, 1] - czm)
                k = int(np.lexsort((dist_c, np.round(dist_edge, 3)))[0])
                if dist_edge[k] > 7:
                    C.warnings.append(f"{s['id']}: nearest walkway is {dist_edge[k]:.1f} m away")
                w = float(dist_c[k]) + (LIFT_BOARDING if s["kind"] == "lift" else 0)
                C.edge(s["id"], ids[k], w)
                if s["kind"] in SELECTABLE_KINDS:
                    C.doors.setdefault(ids[k], []).append(s["id"])

            # lobby on the lowest floor
            if lvl == 0:
                rects = floors[f]["main"]
                bx0, bz0, bx1, bz1 = floors[f].get("region") or _bbox(rects)
                lx, lz = ox + bx0 - 3.0, oz + (bz0 + bz1) / 2
                lid = f"{b}1-LOBBY"
                C.rooms[lid] = {"id": lid, "label": f"Lobby {binfo['name']}", "desc": "Main entrance (assumed)",
                                "b": b, "f": f, "l": lvl, "k": "lobby", "x": round(lx, 2), "z": round(lz, 2),
                                "w": 5.0, "d": 8.0, "plan": floors[f]["plan"]}
                C.pos[lid] = [round(lx, 2), round(lz, 2), lvl, f, b]
                d2 = np.hypot((arr[:, 0] + ox) - lx, (arr[:, 1] + oz) - lz)
                k = int(np.argmin(d2))
                C.edge(lid, ids[k], float(d2[k]))
                floor_room_ids[f].append(lid)
                lobbies[b] = (lx, lz)

            # floor meta for the 3D tiles
            runs = [[round(ox + i0 * GRID + GRID / 2, 2), round(ox + i1 * GRID + GRID / 2, 2),
                     round(oz + j * GRID + GRID / 2, 2)] for (i0, i1, j) in _runs(cells_main | cells_wing)]
            bx = [r for r in specs if r["f"] == f]
            fx0 = min(r["x0"] for r in bx); fx1 = max(r["x1"] for r in bx)
            fz0 = min(r["z0"] for r in bx); fz1 = max(r["z1"] for r in bx)
            if not floors[f]["plan"]:
                fx0, fz0, fx1, fz1 = floors[f]["region"]
            floor_meta.append({"floor": f, "level": lvl, "plan": floors[f]["plan"], "runs": runs,
                               "x0": round(ox + fx0, 2), "x1": round(ox + fx1, 2),
                               "z0": round(oz + fz0, 2), "z1": round(oz + fz1, 2)})

        # ---- vertical edges
        by_shaft = {}
        for s in specs:
            if "shaft" in s:
                by_shaft.setdefault(s["shaft"], []).append(s)
        for shaft, lst in by_shaft.items():
            kind = shaft.split(":")[0]
            lst.sort(key=lambda s: s["f"])
            for s1, s2 in zip(lst, lst[1:]):
                C.edge(s1["id"], s2["id"], VERTICAL[kind] * (s2["f"] - s1["f"]), kind)

        meta_buildings.append({
            "id": b, "name": binfo["name"], "color": binfo["color"],
            "x0": round(ox, 2), "x1": round(ox + main_w, 2),
            "z0": round(oz, 2), "z1": round(oz + total_d, 2), "floors": floor_meta})
        b_depth_end[b] = oz + total_d
        oz = oz + total_d + BUILDING_GAP

    # ---- outdoor walkway from the Main Gate to each lobby
    first = next(iter(lobbies.values()))
    gate_z = min(z for _, z in lobbies.values()) - 26
    C.rooms["GATE"] = {"id": "GATE", "label": "Main Gate", "desc": "Gerbang Utama UNPAM", "b": "Campus", "f": 1,
                       "l": 0, "k": "gate", "x": WALKWAY_X, "z": round(gate_z, 2), "w": 6.0, "d": 6.0, "plan": True}
    C.pos["GATE"] = [WALKWAY_X, round(gate_z, 2), 0, 1, "Campus"]
    outdoor_segments = []
    counter = [0]

    def chain(p0, p1, start_id, end_id):
        """outdoor nodes every NODE_STEP metres between two points"""
        n = max(1, ceil(hypot(p1[0] - p0[0], p1[1] - p0[1]) / NODE_STEP))
        prev = start_id
        for t in range(1, n):
            counter[0] += 1
            nid = f"OUT{counter[0]}"
            x = p0[0] + (p1[0] - p0[0]) * t / n
            z = p0[1] + (p1[1] - p0[1]) * t / n
            C.pos[nid] = [round(x, 2), round(z, 2), 0, 1, "Campus"]
            C.edge(prev, nid, hypot(p1[0] - p0[0], p1[1] - p0[1]) / n, "outdoor")
            prev = nid
        C.edge(prev, end_id, hypot(p1[0] - p0[0], p1[1] - p0[1]) / n, "outdoor")
        outdoor_segments.append([round(p0[0], 2), round(p0[1], 2), round(p1[0], 2), round(p1[1], 2)])

    prev_id, prev_pt = "GATE", (WALKWAY_X, gate_z)
    for b, (lx, lz) in lobbies.items():
        jid = f"WALK-{b}"
        C.pos[jid] = [WALKWAY_X, round(lz, 2), 0, 1, "Campus"]
        chain(prev_pt, (WALKWAY_X, lz), prev_id, jid)
        chain((WALKWAY_X, lz), (lx, lz), jid, f"{b}1-LOBBY")
        prev_id, prev_pt = jid, (WALKWAY_X, lz)

    for b1, b2, fl in SKYBRIDGES:
        pass  # reserved: add an edge between corridor cells of two buildings here

    C.meta = {
        "buildings": meta_buildings, "kinds": KIND_META, "outdoor": outdoor_segments,
        "grid": GRID, "scale": {"main": S_MAIN, "wing": S_WING},
        "assumed": ("Room positions and sizes come from the PDF boxes (estimated at "
                    f"{S_MAIN} m per PDF point, rear wings {S_WING}). Corridors are generated from the free space "
                    "between rooms. Floors B1 and C1, the lobbies and the outdoor walkway are assumptions."),
    }
    return C


def to_adjacency(edges):
    """Edge list -> adjacency list {node: [(neighbour, weight, type), ...]} (undirected)."""
    graph = {}
    for a, b, w, t in edges:
        graph.setdefault(a, []).append((b, w, t))
        graph.setdefault(b, []).append((a, w, t))
    return graph


if __name__ == "__main__":
    import time
    t0 = time.time()
    c = build_campus()
    g = to_adjacency(c.edges)
    print(f"{len(g)} graph nodes, {len(c.edges)} edges, {len(c.rooms)} rooms, built in {time.time() - t0:.1f}s")
    print(len(c.warnings), "warnings", c.warnings[:8])
