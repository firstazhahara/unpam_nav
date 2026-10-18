"""Run:  python -m unittest -v"""
import unittest

from campus_data import build_campus, to_adjacency
from dijkstra import dijkstra


class DijkstraTests(unittest.TestCase):
    def setUp(self):
        self.g = {
            "S": [("A", 1, "walk"), ("B", 4, "walk")],
            "A": [("S", 1, "walk"), ("B", 2, "walk"), ("T", 7, "stairs")],
            "B": [("S", 4, "walk"), ("A", 2, "walk"), ("T", 3, "walk")],
            "T": [("A", 7, "stairs"), ("B", 3, "walk")],
            "X": [],
        }

    def test_shortest_path(self):
        r = dijkstra(self.g, "S", "T")
        self.assertEqual(r["path"], ["S", "A", "B", "T"])
        self.assertEqual(r["distance"], 6)

    def test_blocked_type(self):
        g = {"S": [("T", 1, "stairs")], "T": [("S", 1, "stairs")]}
        self.assertFalse(dijkstra(g, "S", "T", {"stairs"})["found"])

    def test_unreachable(self):
        self.assertFalse(dijkstra(self.g, "S", "X")["found"])


class CampusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = build_campus()
        cls.g = to_adjacency(cls.c.edges)

    def test_all_places_reachable(self):
        seen, stack = {"GATE"}, ["GATE"]
        while stack:
            u = stack.pop()
            for v, _, _ in self.g[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        missing = [i for i, r in self.c.rooms.items() if r["k"] != "void" and i not in seen]
        self.assertEqual(missing, [])

    def test_accessible_routes_avoid_stairs(self):
        blocked = {"stairs", "escalator"}
        for target in ("C8-LABPEMROGRAMAN5", "B9-V932", "A6-V631", "C12-V1061", "B2-V246"):
            r = dijkstra(self.g, "GATE", target, blocked)
            self.assertTrue(r["found"], target)
            self.assertFalse({leg[3] for leg in r["legs"]} & blocked)

    def test_layout_follows_pdf(self):
        """Gedung A floor 1: V.122..V.126 run left to right, V.121 sits below V.122,
        and a classroom box is about 8 x 9.3 m (80 x 93 PDF points at 0.1 m/pt)."""
        r = self.c.rooms
        xs = [r[f"A1-V{n}"]["x"] for n in (122, 123, 124, 125, 126)]
        self.assertEqual(xs, sorted(xs))
        self.assertGreater(r["A1-V121"]["z"], r["A1-V122"]["z"])
        self.assertAlmostEqual(r["A1-V122"]["x"], r["A1-V121"]["x"], delta=0.5)
        self.assertAlmostEqual(r["A1-V122"]["w"], 8.0, delta=0.3)
        self.assertAlmostEqual(r["A1-V122"]["d"], 9.3, delta=0.3)


if __name__ == "__main__":
    unittest.main()
