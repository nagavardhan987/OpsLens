"""
OpsLens - Unit Tests for SOP Retrieval Engine (Component 7)
"""

import unittest
import asyncio
import tempfile
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import Database
from generator import SyntheticDataGenerator
from stream import TagStream
from prioritizer import PrioritizationEngine
from dedup import DeduplicationEngine
from topology import TopologyGraph
from correlator import CorrelationEngine
from event_story import EventStoryConstructor
from evidence_engine import EvidenceEngine
from sop_retriever import SopRetriever


class TestRetrievalEngineUnit(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_retrieval_unit.db"
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
        self.evidence_engine = EvidenceEngine(db=self.db)
        self.retriever = SopRetriever(db=self.db)
        self.generator = SyntheticDataGenerator(
            db=self.db,
            sample_interval=2.0,
            start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
        )

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_end_to_end_retrieval_discrimination(self):
        """Live pipeline end-to-end discrimination test."""
        async def run_pipeline():
            # Scenario A
            self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc))
            self.dedup.clear()
            self.db.clear_correlated_events()
            self.db.clear_event_stories()
            self.db.clear_evidence()
            self.db.clear_sop_matches()

            readings_a = list(self.generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
            for r in readings_a:
                self.dedup.process_reading(r)

            candidates_a = self.db.get_candidate_events()
            correlated_a = await self.correlator.correlate_event(candidates_a[0])
            story_a = self.story_constructor.construct_story(correlated_a, persist=True)
            evidence_a = self.evidence_engine.evaluate_event(correlated_a, persist=True)
            match_a = self.retriever.retrieve(story=story_a, evidence=evidence_a, persist=True)

            self.assertEqual(match_a.sop_id, "SOP-P02-VLV-01")

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
            evidence_b = self.evidence_engine.evaluate_event(correlated_b, persist=True)
            match_b = self.retriever.retrieve(story=story_b, evidence=evidence_b, persist=True)

            self.assertEqual(match_b.sop_id, "SOP-C01-BRG-01")

            # DB assertions
            matches = self.db.get_sop_matches()
            self.assertEqual(len(matches), 2)

            await self.stream.close()

        asyncio.run(run_pipeline())

    def test_bm25_source_logging(self):
        """Verify BM25 fallback explicitly logs source='bm25'."""
        retriever = SopRetriever(db=self.db, force_source="bm25")
        query = "CMP-01-VIB Bearing vibration -> Stator current rise -> Bearing temperature rise -> High vibration alarm"
        match = retriever.retrieve(custom_query=query, persist=False)
        self.assertEqual(match.sop_id, "SOP-C01-BRG-01")
        self.assertEqual(match.source, "bm25")


if __name__ == "__main__":
    unittest.main()
