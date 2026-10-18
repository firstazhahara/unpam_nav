"""
dijkstra.py
-----------
Dijkstra's Shortest Path Algorithm implemented from scratch (no graph library).

* Graph representation : adjacency list  ->  {node: [(neighbor, weight, edge_type), ...]}
* Priority queue       : binary min-heap (Python's heapq)
* Complexity           : O((V + E) log V) time, O(V) extra space
* Accessibility        : edges whose type is in `blocked_types` are skipped while
                         exploring neighbours (e.g. {"stairs", "escalator"}).
"""
import heapq
import time
from math import inf


def dijkstra(graph, start, target, blocked_types=frozenset()):
    """
    Return a dict:
        found          bool
        path           list of node ids from start to target ([] if not found)
        distance       total weight of the path (None if not found)
        legs           list of (u, v, weight, type) along the path
        stats          {"nodes_popped", "edges_relaxed", "elapsed_ms"}
    """
    t0 = time.perf_counter()

    if start not in graph or target not in graph:
        return _result(False, [], None, [], 0, 0, t0)

    dist = {start: 0.0}            # best known distance to each node
    prev = {}                      # node -> (previous node, weight, type)
    visited = set()
    heap = [(0.0, start)]          # (distance, node)
    popped = relaxed = 0

    while heap:
        d, u = heapq.heappop(heap)
        if u in visited:           # stale heap entry (lazy deletion)
            continue
        visited.add(u)
        popped += 1

        if u == target:            # early exit: shortest path to target is final
            break

        for v, w, etype in graph[u]:
            if etype in blocked_types:      # accessibility constraint
                continue
            if v in visited:
                continue
            nd = d + w
            if nd < dist.get(v, inf):       # relaxation
                dist[v] = nd
                prev[v] = (u, w, etype)
                heapq.heappush(heap, (nd, v))
                relaxed += 1

    if target not in visited:
        return _result(False, [], None, [], popped, relaxed, t0)

    # Path reconstruction: O(V)
    path, legs = [target], []
    cur = target
    while cur != start:
        p, w, etype = prev[cur]
        legs.append((p, cur, w, etype))
        path.append(p)
        cur = p
    path.reverse()
    legs.reverse()
    return _result(True, path, dist[target], legs, popped, relaxed, t0)


def _result(found, path, distance, legs, popped, relaxed, t0):
    return {
        "found": found,
        "path": path,
        "distance": distance,
        "legs": legs,
        "stats": {
            "nodes_popped": popped,
            "edges_relaxed": relaxed,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 4),
        },
    }
