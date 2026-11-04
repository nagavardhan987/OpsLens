"""Replaceable industrial relationship graph; NetworkX is optional at runtime."""
from typing import Dict, List


class IndustrialKnowledgeGraph:
    def __init__(self):
        try:
            import networkx as nx
            self._graph = nx.DiGraph()
        except ImportError:
            self._graph = None
        # Prototype relationships for the Pump-02 valve restriction scenario.
        self.add_relationship("Valve-04", "controls", "Flow-02")
        self.add_relationship("Flow-02", "associated_with", "Pump-02")
        self.add_relationship("Pump-02", "driven_by", "Motor-02")
        self.add_relationship("Pump-02", "monitored_by", "Pressure-02")
        for equipment, tag in (("Valve-04", "VLV-04-POS"), ("Flow-02", "FIT-02-FLW"),
                               ("Motor-02", "MOT-02-CUR"), ("Pressure-02", "PIT-02-PRS")):
            self.add_relationship(equipment, "has_sensor", tag)

    def add_relationship(self, source: str, relation: str, target: str) -> None:
        if self._graph is not None:
            self._graph.add_edge(source, target, relation=relation)

    def context(self, equipment: str, tags: List[str]) -> List[str]:
        if self._graph is None: return []
        nodes = {equipment, *tags}
        edges = []
        for source, target, data in self._graph.edges(data=True):
            if source in nodes or target in nodes:
                edges.append(f"{source} --{data.get('relation', 'related_to')}--> {target}")
        return edges
