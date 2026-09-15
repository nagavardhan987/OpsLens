"""
OpsLens - Acceptance Verification for Evidence & Attribution Engine (Component 6)

Validates all acceptance criteria:
1. Scenario (a) Live Pipeline: likely_contributor_tag = VLV-04-POS, confidence_label = HIGH.
2. Synthetic edge case where two tags have near-equal scores produces confidence_label = MEDIUM or LOW,
   not a false HIGH.
3. Full auditability: formula factors and breakdown stored in SQLite evidence table.
"""

import unittest
import asyncio
import tempfile
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import Database
from generator import SyntheticDataGenerator
from stream import TagStream
from prioritizer import PrioritizationEngine
from dedup import DeduplicationEngine
from topology import TopologyGraph
from correlator import CorrelationEngine
from evidence_engine import EvidenceEngine
from models import CorrelatedEvent, CorrelatedDeviation


class TestEvidenceAcceptance(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_evidence_opslens.db"
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

    def test_scenario_a_likely_contributor_and_high_confidence(self):
        """
        Acceptance Criterion 1:
        Scenario (a): likely_contributor_tag = VLV-04-POS (matches existing ground-truth narrative),
        confidence_label = HIGH.
        """
        async def run_pipeline():
            self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc))
            self.dedup.clear()
            self.db.clear_correlated_events()
            self.db.clear_evidence()

            # 1. Stream Scenario A readings into SQLite
            readings = list(self.generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
            for r in readings:
                self.dedup.process_reading(r)

            candidates = self.db.get_candidate_events()
            self.assertEqual(len(candidates), 1)

            # 2. Correlate event via Component 4
            correlated_event = await self.correlator.correlate_event(candidates[0])

            # 3. Evaluate attribution via Component 6 EvidenceEngine
            evidence = self.evidence_engine.evaluate_event(correlated_event, persist=True)

            # Verify Acceptance Criteria
            self.assertEqual(
                evidence.likely_contributor_tag,
                "VLV-04-POS",
                f"Expected root cause VLV-04-POS, got {evidence.likely_contributor_tag}"
            )
            self.assertEqual(
                evidence.confidence_label,
                "HIGH",
                f"Expected HIGH confidence label, got {evidence.confidence_label} (score={evidence.confidence_score})"
            )
            self.assertGreater(evidence.confidence_score, 0.60)

            # Check supporting_deltas
            delta_tags = {d.tag: d for d in evidence.supporting_deltas}
            self.assertIn("VLV-04-POS", delta_tags)
            self.assertEqual(delta_tags["VLV-04-POS"].direction, "down")

            # Verify SQLite persistence and inspectable audit log
            audit = self.db.get_evidence_audit(correlated_event.event_id)
            self.assertIsNotNone(audit)
            self.assertEqual(audit["likely_contributor_tag"], "VLV-04-POS")
            self.assertEqual(audit["confidence_label"], "HIGH")
            self.assertIn("tag_scores", audit["scoring_breakdown"])
            self.assertIn("VLV-04-POS", audit["scoring_breakdown"]["tag_scores"])

            # Verify formula factors in audit log
            vlv_factors = audit["scoring_breakdown"]["tag_scores"]["VLV-04-POS"]["formula_factors"]
            self.assertEqual(vlv_factors["severity_weight"], 0.95)
            self.assertEqual(vlv_factors["temporal_precedence_factor"], 1.2)

            await self.stream.close()

        asyncio.run(run_pipeline())

    def test_synthetic_near_equal_scores_edge_case(self):
        """
        Acceptance Criterion 2:
        A synthetic edge case where two tags have near-equal scores should produce
        confidence_label = MEDIUM or LOW, not a false HIGH.
        """
        # Construct a synthetic CorrelatedEvent with 2 competing tags having near-identical scores
        fixture_event = CorrelatedEvent(
            event_id="test-edge-case-near-equal-001",
            primary_tag="ALM-P02-HP",
            primary_alarm=True,
            trigger_timestamp="2026-09-11T12:00:00Z",
            raw_deviation_pct=50.0,
            clustered_tags=["FIT-02-FLW", "PIT-02-PRS"],
            correlated_deviations=[
                CorrelatedDeviation(
                    tag="FIT-02-FLW",
                    deviation_pct=-30.0,
                    timestamp="2026-09-11T11:58:30Z",
                    precedes_primary=True,
                    topology_distance=2
                ),
                CorrelatedDeviation(
                    tag="PIT-02-PRS",
                    deviation_pct=30.0,
                    timestamp="2026-09-11T11:58:35Z",
                    precedes_primary=True,
                    topology_distance=2
                )
            ]
        )

        evidence = self.evidence_engine.evaluate_event(fixture_event, persist=True)

        # In a 2-way near-tie, dominance ratio is ~50%, which must NOT be HIGH
        self.assertNotEqual(
            evidence.confidence_label,
            "HIGH",
            f"False HIGH produced! Confidence score was {evidence.confidence_score}"
        )
        self.assertIn(
            evidence.confidence_label,
            ["MEDIUM", "LOW"],
            f"Expected MEDIUM or LOW for near-equal split, got {evidence.confidence_label}"
        )
        self.assertLessEqual(evidence.confidence_score, 0.60)

    def test_no_deviations_fallback_low_confidence(self):
        """Edge case: isolated event with zero correlated deviations defaults to LOW."""
        empty_event = CorrelatedEvent(
            event_id="test-empty-devs-002",
            primary_tag="PIT-02-PRS",
            primary_alarm=False,
            trigger_timestamp="2026-09-11T12:00:00Z",
            raw_deviation_pct=60.0,
            clustered_tags=["PIT-02-PRS"],
            correlated_deviations=[]
        )
        evidence = self.evidence_engine.evaluate_event(empty_event, persist=False)
        self.assertEqual(evidence.confidence_label, "LOW")
        self.assertEqual(evidence.confidence_score, 0.0)
        self.assertEqual(evidence.likely_contributor_tag, "PIT-02-PRS")


if __name__ == "__main__":
    unittest.main()
