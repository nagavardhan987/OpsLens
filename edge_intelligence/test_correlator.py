"""
OpsLens - Programmatic Acceptance Verification for Correlation Engine (Component 4)

Chains Components 1, 2, 3, and 4 together with live data (not mocked):
- Component 1: SyntheticDataGenerator streaming real-time TagReadings into SQLite
- Component 2: TagStream providing pub-sub and get_window() lookback queries
- Component 3: Prioritization & DeduplicationEngine producing CandidateEvents
- Component 4: CorrelationEngine enriching CandidateEvents into CorrelatedEvents

Validates all 3 acceptance criteria:
1. Scenario (a): correlated_deviations contains VLV-04-POS, FIT-02-FLW, MOT-02-CUR
   in that temporal order, each with precedes_primary=true.
2. Scenario (b): correlated_deviations does NOT include any Pump-02 tag even if
   timestamps happen to overlap.
3. Scenario (d): correlated_deviations is empty (confirms no false correlation is
   manufactured for an isolated sensor fault).
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


class TestCorrelationAcceptance(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_corr_opslens.db"
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
        self.generator = SyntheticDataGenerator(
            db=self.db,
            sample_interval=2.0,
            start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
        )

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scenario_a_temporal_correlation_cascade(self):
        """
        Acceptance Criterion 1:
        Scenario (a): correlated_deviations contains VLV-04-POS, FIT-02-FLW,
        MOT-02-CUR in that temporal order, each with precedes_primary=true.
        """
        async def run_test():
            self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc))
            self.dedup.clear()
            self.db.clear_correlated_events()

            # 1. Component 1: Stream live scenario readings into SQLite
            readings = list(self.generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))

            # 2. Component 3: Feed live readings into DeduplicationEngine to produce CandidateEvent
            for r in readings:
                self.dedup.process_reading(r)

            candidates = self.db.get_candidate_events()
            self.assertEqual(len(candidates), 1, "Expected 1 CandidateEvent from Component 3")
            candidate = candidates[0]
            self.assertEqual(candidate.primary_tag, "ALM-P02-HP")
            self.assertTrue(candidate.primary_alarm)

            # 3. Component 4: Correlate candidate event using live lookback window via TagStream
            correlated_event = await self.correlator.correlate_event(candidate)

            # Assertions on correlated_deviations
            devs = correlated_event.correlated_deviations
            dev_tags = [d.tag for d in devs]

            # Must contain VLV-04-POS, FIT-02-FLW, MOT-02-CUR
            self.assertIn("VLV-04-POS", dev_tags)
            self.assertIn("FIT-02-FLW", dev_tags)
            self.assertIn("MOT-02-CUR", dev_tags)

            # Check exact temporal precedence order: VLV -> FIT -> MOT
            vlv_idx = dev_tags.index("VLV-04-POS")
            fit_idx = dev_tags.index("FIT-02-FLW")
            mot_idx = dev_tags.index("MOT-02-CUR")
            self.assertTrue(
                vlv_idx < fit_idx < mot_idx,
                f"Expected temporal order [VLV-04-POS, FIT-02-FLW, MOT-02-CUR], got {dev_tags}"
            )

            # Check precedes_primary is True for each
            for d in devs:
                if d.tag in ["VLV-04-POS", "FIT-02-FLW", "MOT-02-CUR"]:
                    self.assertTrue(
                        d.precedes_primary,
                        f"Expected tag {d.tag} to have precedes_primary=True"
                    )
                    self.assertTrue(1 <= d.topology_distance <= 3)

            # Check write-through persistence into SQLite table correlated_events
            persisted = self.db.get_correlated_events()
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0].event_id, candidate.event_id)

            await self.stream.close()

        asyncio.run(run_test())

    def test_scenario_b_equipment_isolation(self):
        """
        Acceptance Criterion 2:
        Scenario (b): correlated_deviations does NOT include any Pump-02 tag even
        if timestamps happen to overlap.
        """
        async def run_test():
            self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 11, 0, 0, tzinfo=timezone.utc))
            self.dedup.clear()
            self.db.clear_correlated_events()

            # 1. Run bearing_wear on Compressor-01
            readings = list(self.generator.run_scenario("bearing_wear", speed_multiplier=float("inf")))
            for r in readings:
                self.dedup.process_reading(r)

            candidates = self.db.get_candidate_events()
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertIn(candidate.primary_tag, ["ALM-C01-VB", "CMP-01-VIB", "CMP-01-CUR", "CMP-01-TMP"])

            # 2. Correlate CandidateEvent
            correlated_event = await self.correlator.correlate_event(candidate)

            dev_tags = [d.tag for d in correlated_event.correlated_deviations]

            # Critical Acceptance Check: No Pump-02 tags can be included!
            pump_tags = {"VLV-04-POS", "FIT-02-FLW", "MOT-02-CUR", "PIT-02-PRS", "ALM-P02-HP"}
            overlap = set(dev_tags) & pump_tags
            self.assertEqual(
                len(overlap), 0,
                f"Spurious correlation breach! Pump-02 tags found in Compressor event: {overlap}"
            )

            # Verify Compressor-01 tags are present
            self.assertTrue(any("CMP" in t for t in dev_tags))

            await self.stream.close()

        asyncio.run(run_test())

    def test_scenario_d_isolated_sensor_fault(self):
        """
        Acceptance Criterion 3:
        Scenario (d): correlated_deviations is empty (confirms no false correlation
        is manufactured for an isolated sensor fault).
        """
        async def run_test():
            self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc))
            self.dedup.clear()
            self.db.clear_correlated_events()

            # 1. Run sensor_fault (isolated spike on PIT-02-PRS)
            readings = list(self.generator.run_scenario("sensor_fault", speed_multiplier=float("inf")))
            for r in readings:
                self.dedup.process_reading(r)

            candidates = self.db.get_candidate_events()
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate.primary_tag, "PIT-02-PRS")

            # 2. Correlate CandidateEvent
            correlated_event = await self.correlator.correlate_event(candidate)

            # Critical Acceptance Check: correlated_deviations must be strictly EMPTY
            self.assertEqual(
                len(correlated_event.correlated_deviations), 0,
                f"Manufactured spurious correlations for isolated sensor fault: {correlated_event.correlated_deviations}"
            )

            await self.stream.close()

        asyncio.run(run_test())


def print_report():
    print("=" * 82)
    print(" OpsLens Component 4: Context Correlation Engine Acceptance Verification")
    print("=" * 82)

    suite = unittest.TestLoader().loadTestsFromTestCase(TestCorrelationAcceptance)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 82)
    if result.wasSuccessful():
        print(" ALL ACCEPTANCE CRITERIA VERIFIED ON LIVE CHAINED PIPELINE: PASSED (3/3)")
    else:
        print(f" VERIFICATION FAILED: {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 82)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    import sys
    sys.exit(print_report())
