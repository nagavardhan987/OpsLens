"""
OpsLens - Unit Tests for EventStory Constructor (Component 5)
"""

import unittest
import asyncio
import tempfile
import shutil
import inspect
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from datetime import datetime, timezone

from database import Database
from generator import SyntheticDataGenerator
from stream import TagStream
from prioritizer import PrioritizationEngine
from dedup import DeduplicationEngine
from topology import TopologyGraph
from correlator import CorrelationEngine
from event_story import EventStoryConstructor
import event_story


class TestEventStory(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_story_unit.db"
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
        self.story_constructor = EventStoryConstructor(db=self.db)
        self.generator = SyntheticDataGenerator(
            db=self.db,
            sample_interval=2.0,
            start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
        )

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_zero_scenario_branching_in_code(self):
        """Verify zero scenario-specific branches in event_story.py."""
        source = inspect.getsource(event_story)
        forbidden_terms = [
            "valve_restriction", "bearing_wear", "seal_leak", "sensor_fault",
            "scenario_a", "scenario_b", "Pump-02", "Compressor-01",
            "VLV-04-POS", "ALM-P02-HP", "ALM-C01-VB"
        ]
        for term in forbidden_terms:
            self.assertNotIn(term.lower(), source.lower())

    def test_causal_chains_differ_and_template_correctly(self):
        """End-to-end verification of generic templating and causal chain generation."""
        async def run_pipeline():
            # Scenario A
            self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc))
            self.dedup.clear()
            self.db.clear_correlated_events()
            self.db.clear_event_stories()

            readings_a = list(self.generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
            for r in readings_a:
                self.dedup.process_reading(r)

            candidates_a = self.db.get_candidate_events()
            correlated_a = await self.correlator.correlate_event(candidates_a[0])
            story_a = self.story_constructor.construct_story(correlated_a, persist=True)

            # Scenario B
            self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 11, 0, 0, tzinfo=timezone.utc))
            self.dedup.clear()
            self.db.clear_correlated_events()

            readings_b = list(self.generator.run_scenario("bearing_wear", speed_multiplier=float("inf")))
            for r in readings_b:
                self.dedup.process_reading(r)

            candidates_b = self.db.get_candidate_events()
            correlated_b = await self.correlator.correlate_event(candidates_b[0])
            story_b = self.story_constructor.construct_story(correlated_b, persist=True)

            # Assertions
            self.assertNotEqual(story_a.causal_label, story_b.causal_label)
            self.assertEqual(
                story_a.causal_label,
                "Valve restriction -> Flow reduction -> Motor current surge -> Pressure surge -> High pressure alarm"
            )
            valid_causal_b = [
                "Bearing vibration -> Stator current rise -> Bearing temperature rise -> High vibration alarm",
                "Bearing vibration -> Bearing temperature rise -> Stator current rise -> High vibration alarm"
            ]
            self.assertIn(story_b.causal_label, valid_causal_b)

            # Check DB retrieval
            stories = self.db.get_event_stories()
            self.assertEqual(len(stories), 2)

            await self.stream.close()

        asyncio.run(run_pipeline())


if __name__ == "__main__":
    unittest.main()
