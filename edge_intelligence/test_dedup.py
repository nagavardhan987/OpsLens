"""
OpsLens - Programmatic Acceptance Verification for Deduplication & Prioritization (Component 3)

Validates all 3 acceptance criteria against Component 1's ground truth:
1. Scenario (a) Valve Restriction Cascade: Exactly ONE CandidateEvent produced,
   clustering all 4 Pump-02 tags plus the alarm tag (flood suppression).
2. Scenario (d) Sensor Fault: Exactly ONE CandidateEvent produced, clustered_tags
   contains ONLY the faulting tag (isolated spike).
3. Scenario (b) and (a) Back-to-Back: Exactly TWO separate CandidateEvents with
   non-overlapping clustered_tags (Compressor-01 bearing tags never appear in Pump-02 event).
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

from models import CandidateEvent
from database import Database
from generator import SyntheticDataGenerator
from prioritizer import PrioritizationEngine
from dedup import DeduplicationEngine


class TestDeduplicationAcceptance(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_dedup_opslens.db"
        self.db = Database(db_path=self.db_path)
        self.prioritizer = PrioritizationEngine()
        self.dedup = DeduplicationEngine(
            db=self.db,
            prioritizer=self.prioritizer,
            cluster_window_seconds=90.0
        )
        self.generator = SyntheticDataGenerator(
            db=self.db,
            sample_interval=2.0,
            start_time=datetime(2026, 9, 11, 14, 0, 0, tzinfo=timezone.utc)
        )

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scenario_a_valve_cascade_flood_suppression(self):
        """
        Acceptance Criterion 1:
        Scenario (a) valve cascade: exactly ONE CandidateEvent produced, with
        clustered_tags containing all 4 Pump-02 tags plus the alarm tag, NOT 5
        separate events.
        """
        self.dedup.clear()

        # Run Scenario A and feed live readings into the deduplication engine
        readings = list(self.generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
        for r in readings:
            self.dedup.process_reading(r)

        # Inspect persisted candidate events in SQLite
        events = self.db.get_candidate_events()

        # Assert flood suppression: Exactly ONE event, not 5 separate events
        self.assertEqual(
            len(events), 1,
            f"Flood suppression failure: expected exactly 1 CandidateEvent, but got {len(events)}"
        )

        event = events[0]
        expected_pump_tags = {
            "VLV-04-POS",
            "FIT-02-FLW",
            "MOT-02-CUR",
            "PIT-02-PRS",
            "ALM-P02-HP"
        }

        # Assert clustered tags contains all 5 tags
        actual_tags = set(event.clustered_tags)
        self.assertEqual(
            actual_tags, expected_pump_tags,
            f"Clustered tags mismatch. Missing: {expected_pump_tags - actual_tags}, Extra: {actual_tags - expected_pump_tags}"
        )

        # Assert primary tag is the critical high-pressure alarm
        self.assertEqual(event.primary_tag, "ALM-P02-HP")
        self.assertTrue(event.primary_alarm, "Expected primary_alarm to be True")

    def test_scenario_d_sensor_fault_isolation(self):
        """
        Acceptance Criterion 2:
        Scenario (d) sensor fault: exactly ONE CandidateEvent, clustered_tags
        contains only the faulting tag.
        """
        self.dedup.clear()
        self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 15, 0, 0, tzinfo=timezone.utc))

        readings = list(self.generator.run_scenario("sensor_fault", speed_multiplier=float("inf")))
        for r in readings:
            self.dedup.process_reading(r)

        events = self.db.get_candidate_events()

        self.assertEqual(
            len(events), 1,
            f"Expected exactly 1 CandidateEvent for isolated sensor fault, but got {len(events)}"
        )

        event = events[0]
        # Must contain ONLY the faulting tag
        self.assertEqual(
            event.clustered_tags, ["PIT-02-PRS"],
            f"Expected clustered_tags to contain only ['PIT-02-PRS'], got {event.clustered_tags}"
        )
        self.assertEqual(event.primary_tag, "PIT-02-PRS")
        # Sensor spike was transient transmitter glitch, not a persistent trip alarm
        self.assertFalse(event.primary_alarm)

    def test_scenario_b_and_a_back_to_back_isolation(self):
        """
        Acceptance Criterion 3:
        Scenario (b) and (a) run back to back: two separate CandidateEvents with
        non-overlapping clustered_tags (bearing tags never appear in the pump event).
        """
        self.dedup.clear()
        self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 16, 0, 0, tzinfo=timezone.utc))

        # 1. Run Scenario B (Compressor Bearing Wear)
        b_readings = list(self.generator.run_scenario("bearing_wear", speed_multiplier=float("inf")))
        for r in b_readings:
            self.dedup.process_reading(r)

        # 2. Run Scenario A (Pump-02 Valve Cascade)
        a_readings = list(self.generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
        for r in a_readings:
            self.dedup.process_reading(r)

        events = self.db.get_candidate_events()

        # Must produce exactly TWO distinct CandidateEvents
        self.assertEqual(
            len(events), 2,
            f"Expected exactly 2 CandidateEvents for two distinct equipment incidents, got {len(events)}"
        )

        # Separate into Compressor event and Pump event
        comp_events = [e for e in events if any("CMP" in t for t in e.clustered_tags)]
        pump_events = [e for e in events if any("VLV" in t or "PIT" in t for t in e.clustered_tags)]

        self.assertEqual(len(comp_events), 1, "Expected 1 Compressor event")
        self.assertEqual(len(pump_events), 1, "Expected 1 Pump event")

        comp_tags = set(comp_events[0].clustered_tags)
        pump_tags = set(pump_events[0].clustered_tags)

        # Assert complete isolation / disjoint sets
        self.assertTrue(
            comp_tags.isdisjoint(pump_tags),
            f"Equipment contamination detected! Overlap: {comp_tags & pump_tags}"
        )

        # Assert expected tags for each equipment
        expected_comp_tags = {"CMP-01-VIB", "CMP-01-CUR", "CMP-01-TMP", "ALM-C01-VB"}
        self.assertEqual(comp_tags, expected_comp_tags)

        expected_pump_tags = {"VLV-04-POS", "FIT-02-FLW", "MOT-02-CUR", "PIT-02-PRS", "ALM-P02-HP"}
        self.assertEqual(pump_tags, expected_pump_tags)


def print_report():
    print("=" * 82)
    print(" OpsLens Component 3: Prioritization & Deduplication Acceptance Verification")
    print("=" * 82)

    suite = unittest.TestLoader().loadTestsFromTestCase(TestDeduplicationAcceptance)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 82)
    if result.wasSuccessful():
        print(" ALL ACCEPTANCE CRITERIA VERIFIED PROGRAMMATICALLY: PASSED (3/3)")
    else:
        print(f" VERIFICATION FAILED: {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 82)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    import sys
    sys.exit(print_report())
