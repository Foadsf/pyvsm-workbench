from typing import Dict

class DisjointSet:
    """Union-Find structure for grouping connected schematic pins into electrical nets."""

    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.parent[item] = item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, a: str, b: str):
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a != root_b:
            # Canonical net priorities: prefer lower number / ground / power / known buses
            priority = {
                "0": 0, "gnd": 0,
                "vcc": 1,
                "adc0": 2,
                "pb0": 3,
                "pb2": 4,
                "v_load": 5,
                "scl": 6,
                "sda": 7,
                "txd": 8,
                "rxd": 9,
            }
            pa = priority.get(root_a.lower(), 99)
            pb = priority.get(root_b.lower(), 99)
            if pa <= pb:
                self.parent[root_b] = root_a
            else:
                self.parent[root_a] = root_b
