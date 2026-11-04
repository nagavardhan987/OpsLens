"""
OpsLens - Causal Topology Graph Engine (Component 4)

Constructs and traverses the plant causal DAG from TagRegistryEntry metadata.
Calculates topological distances (hop counts) between tags to score plausibility
and prevent spurious correlation of unrelated physical tags.
"""

from collections import deque
from typing import Dict, List, Optional, Set, Tuple
from registry_loader import RegistryLoader, get_registry_loader
from models import TagRegistryEntry


class TopologyGraph:
    """
    Causal Directed Acyclic Graph (DAG) for industrial asset telemetry.
    Edges represent causal dependencies: Upstream Tag -> Downstream Tag.
    """

    def __init__(self, registry_loader: Optional[RegistryLoader] = None):
        self.loader = registry_loader if registry_loader is not None else get_registry_loader()
        self._upstream_adj: Dict[str, List[str]] = {}
        self._downstream_adj: Dict[str, List[str]] = {}
        self._equipment_map: Dict[str, str] = {}
        self._build_graph()

    def _build_graph(self) -> None:
        """Construct adjacency maps from registry loader."""
        all_tags = self.loader.all_tags()
        self._upstream_adj = {t: [] for t in all_tags}
        self._downstream_adj = {t: [] for t in all_tags}

        for tag in all_tags:
            entry = self.loader.get_tag(tag)
            self._equipment_map[tag] = entry.equipment_id
            for up in entry.topology_upstream:
                if up in self._upstream_adj:
                    self._upstream_adj[tag].append(up)
                    self._downstream_adj[up].append(tag)

    def get_equipment_id(self, tag: str) -> Optional[str]:
        """Return equipment ID for tag."""
        return self._equipment_map.get(tag)

    def get_upstream_nodes(self, tag: str, max_depth: int = 3) -> Dict[str, int]:
        """
        Traverse upstream causal links via BFS up to max_depth.
        Returns a dict mapping tag -> shortest hop distance (1 = direct upstream).
        """
        if tag not in self._upstream_adj:
            return {}

        distances: Dict[str, int] = {}
        queue: deque[Tuple[str, int]] = deque([(tag, 0)])
        visited: Set[str] = {tag}

        while queue:
            curr, dist = queue.popleft()
            if dist > 0:
                distances[curr] = dist

            if dist < max_depth:
                for up in self._upstream_adj.get(curr, []):
                    if up not in visited:
                        visited.add(up)
                        queue.append((up, dist + 1))

        return distances

    def get_downstream_nodes(self, tag: str, max_depth: int = 3) -> Dict[str, int]:
        """
        Traverse downstream causal links via BFS up to max_depth.
        Returns a dict mapping tag -> shortest hop distance (1 = direct downstream).
        """
        if tag not in self._downstream_adj:
            return {}

        distances: Dict[str, int] = {}
        queue: deque[Tuple[str, int]] = deque([(tag, 0)])
        visited: Set[str] = {tag}

        while queue:
            curr, dist = queue.popleft()
            if dist > 0:
                distances[curr] = dist

            if dist < max_depth:
                for down in self._downstream_adj.get(curr, []):
                    if down not in visited:
                        visited.add(down)
                        queue.append((down, dist + 1))

        return distances

    def get_distance(self, primary_tag: str, candidate_tag: str, max_depth: int = 3) -> Optional[int]:
        """
        Calculate topological distance (number of hops) from primary_tag to candidate_tag.
        - 0: same tag
        - 1: direct upstream (or direct downstream)
        - 2..max_depth: multi-hop causal connection
        - None: unreachable or exceeds max_depth (e.g. across isolated equipment)
        """
        if primary_tag == candidate_tag:
            return 0

        # Check upstream causal path (primary causally depends on candidate)
        upstream_map = self.get_upstream_nodes(primary_tag, max_depth=max_depth)
        if candidate_tag in upstream_map:
            return upstream_map[candidate_tag]

        # Check downstream causal path (candidate causally depends on primary)
        downstream_map = self.get_downstream_nodes(primary_tag, max_depth=max_depth)
        if candidate_tag in downstream_map:
            return downstream_map[candidate_tag]

        # Undirected / common-cause path check within same equipment
        # e.g., both PIT-02 and MOT-02 depend on FIT-02
        if (
            self.get_equipment_id(primary_tag) == self.get_equipment_id(candidate_tag)
            and self.get_equipment_id(primary_tag) is not None
        ):
            # Check undirected BFS distance within the equipment subgraph
            queue = deque([(primary_tag, 0)])
            visited = {primary_tag}
            while queue:
                curr, dist = queue.popleft()
                if curr == candidate_tag:
                    return dist if dist <= max_depth else None

                if dist < max_depth:
                    neighbors = self._upstream_adj.get(curr, []) + self._downstream_adj.get(curr, [])
                    for n in neighbors:
                        if n not in visited and self.get_equipment_id(n) == self.get_equipment_id(primary_tag):
                            visited.add(n)
                            queue.append((n, dist + 1))

        return None

    def is_reachable(self, primary_tag: str, candidate_tag: str, max_depth: int = 3) -> bool:
        """Check if candidate_tag is within max_depth hops of primary_tag."""
        dist = self.get_distance(primary_tag, candidate_tag, max_depth=max_depth)
        return dist is not None and dist <= max_depth
