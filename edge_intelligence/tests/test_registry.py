"""
Tests for Tag Registry and Causal Topology
"""

import unittest
from models import TagRegistryEntry
from tag_registry import (
    TAG_REGISTRY,
    get_tag_entry,
    get_all_tags,
    get_equipment_tags,
    get_all_equipment_ids,
    get_upstream_tags,
    get_downstream_tags,
    get_topology_distance,
    to_registry_dict,
)


class TestTagRegistry(unittest.TestCase):

    def test_registry_size_and_units(self):
        """Requirement 1: 8-12 tags across at least 2-3 equipment units."""
        tags = get_all_tags()
        self.assertTrue(8 <= len(tags) <= 12, f"Expected 8-12 tags, found {len(tags)}")

        equipment_ids = get_all_equipment_ids()
        self.assertTrue(len(equipment_ids) >= 2, f"Expected at least 2-3 equipment units, found {len(equipment_ids)}")
        self.assertIn("Pump-02", equipment_ids)
        self.assertIn("Compressor-01", equipment_ids)
        self.assertIn("Tank-01", equipment_ids)

    def test_tag_schema_compliance(self):
        """All entries must strictly match TagRegistryEntry schema."""
        for tag_name, entry in TAG_REGISTRY.items():
            self.assertIsInstance(entry, TagRegistryEntry)
            self.assertEqual(entry.tag, tag_name)
            self.assertIn(entry.data_type, ["float", "bool", "string"])
            self.assertTrue(0.0 <= entry.severity_weight <= 1.0)
            self.assertTrue(entry.baseline_min <= entry.baseline_max)
            self.assertIsInstance(entry.topology_upstream, list)

            # Dictionary serialization conforms to schema
            d = entry.to_dict()
            self.assertIn("tag", d)
            self.assertIn("equipment_id", d)
            self.assertIn("unit", d)
            self.assertIn("data_type", d)
            self.assertIn("baseline_min", d)
            self.assertIn("baseline_max", d)
            self.assertIn("trip_threshold", d)
            self.assertIn("severity_weight", d)
            self.assertIn("topology_upstream", d)

    def test_topology_dag_acyclic(self):
        """Topology graph must be a valid Directed Acyclic Graph (DAG)."""
        visited = set()
        rec_stack = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for upstream in TAG_REGISTRY[node].topology_upstream:
                if upstream not in visited:
                    if has_cycle(upstream):
                        return True
                elif upstream in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        for tag in TAG_REGISTRY:
            if tag not in visited:
                self.assertFalse(has_cycle(tag), f"Topology cycle detected involving tag {tag}")

    def test_topology_helpers(self):
        """Test upstream, downstream, and distance helpers."""
        fit_up = get_upstream_tags("FIT-02-FLW", recursive=False)
        self.assertEqual(fit_up, ["VLV-04-POS"])

        alm_up_all = get_upstream_tags("ALM-P02-HP", recursive=True)
        self.assertIn("PIT-02-PRS", alm_up_all)
        self.assertIn("FIT-02-FLW", alm_up_all)
        self.assertIn("VLV-04-POS", alm_up_all)

        dist = get_topology_distance("VLV-04-POS", "ALM-P02-HP")
        self.assertIsNotNone(dist)
        self.assertGreaterEqual(dist, 2)

        # Compressor tag should NOT reach Pump-02 tag
        dist_cross = get_topology_distance("CMP-01-VIB", "ALM-P02-HP")
        self.assertIsNone(dist_cross)


if __name__ == "__main__":
    unittest.main()
