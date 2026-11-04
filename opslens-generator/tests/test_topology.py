"""
Unit tests for TopologyGraph and DAG distance computation (Component 4)
"""

import unittest
from topology import TopologyGraph
from registry_loader import get_registry_loader


class TestTopologyGraph(unittest.TestCase):

    def setUp(self):
        self.topology = TopologyGraph(get_registry_loader())

    def test_direct_upstream_distance(self):
        # ALM-P02-HP depends on PIT-02-PRS -> distance 1
        dist = self.topology.get_distance("ALM-P02-HP", "PIT-02-PRS")
        self.assertEqual(dist, 1)

    def test_multi_hop_upstream_distance(self):
        # ALM-P02-HP -> PIT-02-PRS -> FIT-02-FLW -> VLV-04-POS
        dist_fit = self.topology.get_distance("ALM-P02-HP", "FIT-02-FLW")
        self.assertEqual(dist_fit, 2)

        dist_vlv = self.topology.get_distance("ALM-P02-HP", "VLV-04-POS")
        self.assertEqual(dist_vlv, 3)

    def test_self_distance_zero(self):
        dist = self.topology.get_distance("ALM-P02-HP", "ALM-P02-HP")
        self.assertEqual(dist, 0)

    def test_unreachable_cross_equipment(self):
        # Pump tag to Compressor tag -> None
        dist = self.topology.get_distance("ALM-P02-HP", "CMP-01-VIB")
        self.assertIsNone(dist)

    def test_max_depth_cutoff(self):
        # Upstream nodes with max_depth=2 should not reach VLV-04-POS (which is 3 hops away)
        nodes_depth_2 = self.topology.get_upstream_nodes("ALM-P02-HP", max_depth=2)
        self.assertIn("PIT-02-PRS", nodes_depth_2)
        self.assertIn("FIT-02-FLW", nodes_depth_2)
        self.assertNotIn("VLV-04-POS", nodes_depth_2)

        # With max_depth=3, VLV-04-POS must be reached
        nodes_depth_3 = self.topology.get_upstream_nodes("ALM-P02-HP", max_depth=3)
        self.assertIn("VLV-04-POS", nodes_depth_3)
        self.assertEqual(nodes_depth_3["VLV-04-POS"], 3)


if __name__ == "__main__":
    unittest.main()
