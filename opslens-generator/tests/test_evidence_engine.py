"""
OpsLens - Unit Tests for Evidence & Attribution Engine (Component 6)
"""

import unittest
import asyncio
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

from database import Database
from generator import SyntheticDataGenerator
from stream import TagStream
from prioritizer import PrioritizationEngine
from dedup import DeduplicationEngine
from topology import TopologyGraph
from correlator import CorrelationEngine
from evidence_engine import EvidenceEngine
from models import CorrelatedEvent, CorrelatedDeviation


class TestEvidenceEngineUnit(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_evidence_unit.db"
        self.db = Database(db_path=self.db_path)
        self.stream = TagStream(db_path=self.db_path)
        self.prioritizer = PrioritizationEngine()
        self.dedup = DeduplicationEngine(db=self.db, prioritizer=self.prioritizer)
        self.topology = TopologyGraph()
        self.correlator = CorrelationEngine(
            stream=self.stream,
            db=self.db,
            topology_graph=self.topology,
            noise_threshold_pct=5.0,
            lookback_seconds=120.0
        )
        self.evidence_engine = EvidenceEngine(db=self.db)
        self.generator = SyntheticDataGenerator(
            db=self.db,
            sample_interval=2.0,
            start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
        )

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scenario_a_attribution_pipeline(self):
        """Live pipeline end-to-end attribution test on Scenario A."""
        async def run_pipeline():
            self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc))
            self.dedup.clear()
            self.db.clear_correlated_events()
            self.db.clear_evidence()

            readings = list(self.generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
            for r in readings:
                self.dedup.process_reading(r)

            candidates = self.db.get_candidate_events()
            correlated_event = await self.correlator.correlate_event(candidates[0])
            evidence = self.evidence_engine.evaluate_event(correlated_event, persist=True)

            self.assertEqual(evidence.likely_contributor_tag, "VLV-04-POS")
            self.assertEqual(evidence.confidence_label, "HIGH")
            self.assertGreater(evidence.confidence_score, 0.60)

            # Check DB persistence
            persisted = self.db.get_evidence()
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0].likely_contributor_tag, "VLV-04-POS")

            await self.stream.close()

        asyncio.run(run_pipeline())

    def test_near_equal_scores_prevents_false_high(self):
        """Synthetic edge case where two tags have near-equal scores produces MEDIUM/LOW."""
        fixture = CorrelatedEvent(
            event_id="test-near-equal-split",
            primary_tag="ALM-P02-HP",
            primary_alarm=True,
            trigger_timestamp="2026-09-11T12:00:00Z",
            raw_deviation_pct=50.0,
            clustered_tags=["FIT-02-FLW", "PIT-02-PRS"],
            correlated_deviations=[
                CorrelatedDeviation(
                    tag="FIT-02-FLW",
                    deviation_pct=-25.0,
                    timestamp="2026-09-11T11:58:30Z",
                    precedes_primary=True,
                    topology_distance=2
                ),
                CorrelatedDeviation(
                    tag="PIT-02-PRS",
                    deviation_pct=25.0,
                    timestamp="2026-09-11T11:58:35Z",
                    precedes_primary=True,
                    topology_distance=2
                )
            ]
        )
        evidence = self.evidence_engine.evaluate_event(fixture, persist=True)
        self.assertNotEqual(evidence.confidence_label, "HIGH")
        self.assertIn(evidence.confidence_label, ["MEDIUM", "LOW"])
        self.assertLessEqual(evidence.confidence_score, 0.60)

    def test_empty_deviations_defaults_low(self):
        """Isolated candidate event with zero deviations defaults to LOW."""
        empty_event = CorrelatedEvent(
            event_id="test-empty-003",
            primary_tag="CMP-01-VIB",
            primary_alarm=False,
            trigger_timestamp="2026-09-11T12:00:00Z",
            raw_deviation_pct=40.0,
            clustered_tags=["CMP-01-VIB"],
            correlated_deviations=[]
        )
        evidence = self.evidence_engine.evaluate_event(empty_event, persist=False)
        self.assertEqual(evidence.confidence_label, "LOW")
        self.assertEqual(evidence.confidence_score, 0.0)
        self.assertEqual(evidence.likely_contributor_tag, "CMP-01-VIB")


if __name__ == "__main__":
    unittest.main()
