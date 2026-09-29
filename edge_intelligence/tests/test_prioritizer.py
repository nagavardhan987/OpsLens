"""
Unit tests for PrioritizationEngine and DeduplicationEngine components
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

from models import TagReading
from database import Database
from tag_registry import TAG_REGISTRY
from prioritizer import PrioritizationEngine, DeviationAssessment
from dedup import DeduplicationEngine


class TestPrioritizerUnit(unittest.TestCase):

    def setUp(self):
        self.prioritizer = PrioritizationEngine()

    def test_dynamic_midpoint_and_deviation(self):
        # PIT-02-PRS: min 4.2, max 5.2 -> midpoint 4.7
        entry = TAG_REGISTRY["PIT-02-PRS"]
        mid = self.prioritizer.compute_midpoint(entry)
        self.assertAlmostEqual(mid, 4.7, places=2)

        # Test nominal value (4.7) -> deviation 0.0%
        reading_nom = TagReading(
            tag="PIT-02-PRS",
            value=4.7,
            timestamp="2026-09-11T12:00:00Z",
            unit="bar",
            equipment_id="Pump-02"
        )
        assess_nom = self.prioritizer.evaluate_reading(reading_nom)
        self.assertAlmostEqual(assess_nom.deviation_pct, 0.0, places=1)
        self.assertFalse(assess_nom.is_breach)

        # Test incident value (6.9 bar) -> trip limit 6.5 breached!
        reading_inc = TagReading(
            tag="PIT-02-PRS",
            value=6.9,
            timestamp="2026-09-11T12:00:10Z",
            unit="bar",
            equipment_id="Pump-02"
        )
        assess_inc = self.prioritizer.evaluate_reading(reading_inc)
        self.assertTrue(assess_inc.is_breach)
        self.assertTrue(assess_inc.is_trip_alarm)
        self.assertGreater(assess_inc.deviation_pct, 40.0)

    def test_boolean_alarm_evaluation(self):
        reading_false = TagReading(
            tag="ALM-P02-HP",
            value=False,
            timestamp="2026-09-11T12:00:00Z",
            unit="status",
            equipment_id="Pump-02"
        )
        assess_false = self.prioritizer.evaluate_reading(reading_false)
        self.assertFalse(assess_false.is_breach)
        self.assertFalse(assess_false.is_trip_alarm)

        reading_true = TagReading(
            tag="ALM-P02-HP",
            value=True,
            timestamp="2026-09-11T12:00:02Z",
            unit="status",
            equipment_id="Pump-02"
        )
        assess_true = self.prioritizer.evaluate_reading(reading_true)
        self.assertTrue(assess_true.is_breach)
        self.assertTrue(assess_true.is_trip_alarm)
        self.assertEqual(assess_true.deviation_pct, 100.0)


class TestDeduplicationUnit(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db = Database(db_path=Path(self.temp_dir) / "test_dedup_unit.db")
        self.dedup = DeduplicationEngine(db=self.db, cluster_window_seconds=90.0)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_window_expiration(self):
        """Breaches occurring > 90s apart should start separate clusters."""
        r1 = TagReading(
            tag="PIT-02-PRS",
            value=7.0,  # breached
            timestamp="2026-09-11T12:00:00Z",
            unit="bar",
            equipment_id="Pump-02"
        )
        # 120s later (> 90s window)
        r2 = TagReading(
            tag="VLV-04-POS",
            value=43.0,  # breached
            timestamp="2026-09-11T12:02:00Z",
            unit="%",
            equipment_id="Pump-02"
        )

        self.dedup.process_reading(r1)
        self.dedup.process_reading(r2)

        events = self.db.get_candidate_events()
        self.assertEqual(len(events), 2, "Expected 2 separate events due to window expiration")


if __name__ == "__main__":
    unittest.main()
