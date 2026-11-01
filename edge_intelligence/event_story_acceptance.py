"""
OpsLens - Programmatic Acceptance Verification for EventStory Constructor (Component 5)

Chains Components 1, 2, 3, 4, and 5 together with live data (not mocked):
- Component 1: SyntheticDataGenerator streaming real-time TagReadings into SQLite
- Component 2: TagStream providing pub-sub and get_window() lookback queries
- Component 3: Prioritization & DeduplicationEngine producing CandidateEvents
- Component 4: CorrelationEngine enriching CandidateEvents into CorrelatedEvents
- Component 5: EventStoryConstructor generating human-facing EventStories

Validates acceptance criteria:
1. Scenario (b)'s correlated event produces a DIFFERENT causal_label and step
   sequence than Scenario (a)'s, purely from generic templating.
2. Verified zero scenario-specific if/else branches or hardcoded tag/scenario
   strings inside `event_story.py`.
3. EventStory is correctly persisted to SQLite table `event_stories`.
"""

import unittest
import asyncio
import tempfile
import shutil
import inspect
from pathlib import Path
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


class TestEventStoryAcceptance(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_story_opslens.db"
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

    def test_zero_scenario_branching_in_event_story_code(self):
        """
        Acceptance Criteria: Verify zero scenario-specific if/else branches
        or hardcoded scenario strings exist in event_story.py.
        """
        source = inspect.getsource(event_story)
        forbidden_terms = [
            "valve_restriction",
            "bearing_wear",
            "seal_leak",
            "sensor_fault",
            "scenario_a",
            "scenario_b",
            "scenario_c",
            "scenario_d",
            "Pump-02",
            "Compressor-01",
            "Tank-01",
            "VLV-04-POS",
            "ALM-P02-HP",
            "ALM-C01-VB",
            "CMP-01-VIB",
        ]
        for term in forbidden_terms:
            self.assertNotIn(
                term.lower(),
                source.lower(),
                f"Forbidden scenario-specific term '{term}' found in event_story.py!"
            )

    def test_scenarios_produce_different_stories_via_generic_templating(self):
        """
        Acceptance Criteria: Running against scenario (b)'s correlated event
        produces a DIFFERENT causal_label and step sequence than scenario (a)'s,
        purely from generic templating.
        """
        async def run_pipeline():
            # -------------------------------------------------------------
            # Pipeline Run 1: Scenario A (Pump-02 Valve Restriction Cascade)
            # -------------------------------------------------------------
            self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc))
            self.dedup.clear()
            self.db.clear_correlated_events()
            self.db.clear_event_stories()

            readings_a = list(self.generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
            for r in readings_a:
                self.dedup.process_reading(r)

            candidates_a = self.db.get_candidate_events()
            self.assertEqual(len(candidates_a), 1)
            correlated_a = await self.correlator.correlate_event(candidates_a[0])
            story_a = self.story_constructor.construct_story(correlated_a, persist=True)

            # -------------------------------------------------------------
            # Pipeline Run 2: Scenario B (Compressor-01 Bearing Degradation)
            # -------------------------------------------------------------
            self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 11, 0, 0, tzinfo=timezone.utc))
            self.dedup.clear()
            self.db.clear_correlated_events()

            readings_b = list(self.generator.run_scenario("bearing_wear", speed_multiplier=float("inf")))
            for r in readings_b:
                self.dedup.process_reading(r)

            candidates_b = self.db.get_candidate_events()
            self.assertEqual(len(candidates_b), 1)
            correlated_b = await self.correlator.correlate_event(candidates_b[0])
            story_b = self.story_constructor.construct_story(correlated_b, persist=True)

            # -------------------------------------------------------------
            # Verify Stories Differ Completely
            # -------------------------------------------------------------
            self.assertNotEqual(story_a.event_id, story_b.event_id)
            self.assertNotEqual(story_a.causal_label, story_b.causal_label)
            self.assertNotEqual(len(story_a.steps), 0)
            self.assertNotEqual(len(story_b.steps), 0)

            # Step tags must be completely different
            tags_a = [s.tag for s in story_a.steps]
            tags_b = [s.tag for s in story_b.steps]
            self.assertFalse(set(tags_a).intersection(set(tags_b)),
                            f"Stories shared tags unexpectedly: {set(tags_a) & set(tags_b)}")

            # Check Scenario A causal arrow-chain:
            # Expected sequence: Valve restriction -> Flow reduction -> Motor current surge -> Pressure surge -> High pressure alarm
            expected_causal_a = "Valve restriction -> Flow reduction -> Motor current surge -> Pressure surge -> High pressure alarm"
            self.assertEqual(story_a.causal_label, expected_causal_a)
            # Check Scenario B causal arrow-chain contains Compressor tags in causal order:
            valid_causal_b = [
                "Bearing vibration -> Stator current rise -> Bearing temperature rise -> High vibration alarm",
                "Bearing vibration -> Bearing temperature rise -> Stator current rise -> High vibration alarm"
            ]
            self.assertIn(story_b.causal_label, valid_causal_b)

            # Check step numbering is strictly sequential starting from 1
            for story in [story_a, story_b]:
                for idx, step in enumerate(story.steps, start=1):
                    self.assertEqual(step.step_number, idx)
                    self.assertIsInstance(step.value_before, float)
                    self.assertIsInstance(step.value_after, float)
                    self.assertTrue(len(step.description) > 0)
                    self.assertTrue(len(step.timestamp) > 0)

            # Check SQLite persistence
            persisted_stories = self.db.get_event_stories()
            self.assertEqual(len(persisted_stories), 2)
            persisted_ids = {s.event_id for s in persisted_stories}
            self.assertIn(story_a.event_id, persisted_ids)
            self.assertIn(story_b.event_id, persisted_ids)

            await self.stream.close()

        asyncio.run(run_pipeline())


if __name__ == "__main__":
    unittest.main()
