"""
OpsLens - Programmatic Acceptance Verification for SOP Retrieval Engine (Component 7)

Chains all components together:
- Component 1: Generator
- Component 2: Stream
- Component 3: Prioritization & Deduplication
- Component 4: Context Correlation Engine
- Component 5: EventStory Constructor
- Component 6: Evidence & Attribution Engine
- Component 7: SOP Retrieval Engine

Validates acceptance criteria:
1. Feeding Scenario (a)'s live event correctly retrieves the valve-restriction SOP (SOP-P02-VLV-01),
   NOT the bearing-wear SOP (SOP-C01-BRG-01), with match_score clearly higher for the correct document.
2. Feeding Scenario (b)'s live event retrieves the bearing-wear SOP (SOP-C01-BRG-01) instead.
3. Proves retrieval numerically discriminates between documents (top score exceeds distractor).
4. Tests BM25 fallback mode explicitly, verifying SopMatch.source logging and correct retrieval.
5. Verifies persistence to SQLite table `sop_matches`.
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
from event_story import EventStoryConstructor
from evidence_engine import EvidenceEngine
from sop_retriever import SopRetriever


class TestRetrievalAcceptance(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_retrieval_opslens.db"
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

    def test_scenario_a_and_b_discrimination(self):
        """
        Acceptance Criteria:
        - Feeding scenario (a)'s event correctly retrieves the valve-restriction SOP,
          NOT the bearing-wear SOP, with match_score clearly higher for the correct document.
        - Feeding scenario (b)'s event retrieves the bearing-wear SOP instead.
        - Numerical discrimination verified across both incidents.
        """
        async def run_pipeline():
            # -------------------------------------------------------------
            # Pipeline Run 1: Scenario A (Valve Restriction Cascade)
            # -------------------------------------------------------------
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

            # Retrieve SOP for Scenario A
            match_a = self.retriever.retrieve(story=story_a, evidence=evidence_a, persist=True)

            # -------------------------------------------------------------
            # Pipeline Run 2: Scenario B (Bearing Wear Degradation)
            # -------------------------------------------------------------
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

            # Retrieve SOP for Scenario B
            match_b = self.retriever.retrieve(story=story_b, evidence=evidence_b, persist=True)

            # -------------------------------------------------------------
            # Verify Scenario A Assertions
            # -------------------------------------------------------------
            self.assertEqual(
                match_a.sop_id, "SOP-P02-VLV-01",
                f"Scenario A failed to retrieve valve SOP: got {match_a.sop_id}"
            )
            self.assertNotEqual(
                match_a.sop_id, "SOP-C01-BRG-01",
                "Scenario A incorrectly retrieved bearing wear SOP!"
            )
            self.assertIn("Pump-02", match_a.sop_title)
            self.assertGreater(match_a.match_score, 0.40)
            self.assertGreaterEqual(len(match_a.steps), 5)

            # -------------------------------------------------------------
            # Verify Scenario B Assertions
            # -------------------------------------------------------------
            self.assertEqual(
                match_b.sop_id, "SOP-C01-BRG-01",
                f"Scenario B failed to retrieve bearing SOP: got {match_b.sop_id}"
            )
            self.assertNotEqual(
                match_b.sop_id, "SOP-P02-VLV-01",
                "Scenario B incorrectly retrieved valve restriction SOP!"
            )
            self.assertIn("Compressor-01", match_b.sop_title)
            self.assertGreater(match_b.match_score, 0.40)
            self.assertGreaterEqual(len(match_b.steps), 5)

            # -------------------------------------------------------------
            # Numerical Discrimination Verification
            # -------------------------------------------------------------
            query_a = self.retriever.build_query(story_a, evidence_a)
            ranked_a = self.retriever.get_all_ranked_scores(query_a)
            scores_by_id_a = {item["sop_id"]: item["score"] for item in ranked_a}
            self.assertGreater(
                scores_by_id_a["SOP-P02-VLV-01"],
                scores_by_id_a["SOP-C01-BRG-01"] + 0.20,
                f"Expected clear numerical margin for Scenario A: {scores_by_id_a}"
            )

            query_b = self.retriever.build_query(story_b, evidence_b)
            ranked_b = self.retriever.get_all_ranked_scores(query_b)
            scores_by_id_b = {item["sop_id"]: item["score"] for item in ranked_b}
            self.assertGreater(
                scores_by_id_b["SOP-C01-BRG-01"],
                scores_by_id_b["SOP-P02-VLV-01"] + 0.20,
                f"Expected clear numerical margin for Scenario B: {scores_by_id_b}"
            )

            # -------------------------------------------------------------
            # SQLite Persistence Verification
            # -------------------------------------------------------------
            saved_matches = self.db.get_sop_matches()
            self.assertEqual(len(saved_matches), 2)
            saved_ids = {m.sop_id for m in saved_matches}
            self.assertEqual(saved_ids, {"SOP-P02-VLV-01", "SOP-C01-BRG-01"})

            await self.stream.close()

        asyncio.run(run_pipeline())

    def test_bm25_fallback_retrieval(self):
        """
        Requirement 2: Verify BM25 fallback path operates correctly,
        produces valid discrimination, and logs source='bm25'.
        """
        bm25_retriever = SopRetriever(db=self.db, force_source="bm25")

        # Query simulating Scenario A
        query_a = "VLV-04-POS ALM-P02-HP Valve restriction -> Flow reduction -> Motor current surge -> Pressure surge -> High pressure alarm"
        match_a = bm25_retriever.retrieve(
            story=None,
            evidence=None,
            custom_query=query_a,
            persist=False
        )
        self.assertEqual(match_a.sop_id, "SOP-P02-VLV-01")
        self.assertEqual(match_a.source, "bm25")
        self.assertGreater(match_a.match_score, 0.50)

        # Query simulating Scenario B
        query_b = "CMP-01-VIB ALM-C01-VB Bearing vibration -> Stator current rise -> Bearing temperature rise -> High vibration alarm"
        match_b = bm25_retriever.retrieve(
            story=None,
            evidence=None,
            custom_query=query_b,
            persist=False
        )
        self.assertEqual(match_b.sop_id, "SOP-C01-BRG-01")
        self.assertEqual(match_b.source, "bm25")
        self.assertGreater(match_b.match_score, 0.50)


if __name__ == "__main__":
    unittest.main()
