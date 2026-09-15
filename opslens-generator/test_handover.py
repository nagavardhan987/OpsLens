"""
OpsLens - Shift Handover Compiler Acceptance Verification (Component 10)

Verifies:
1. Mixed Resolved/Open Events: Scenarios (a) and (b) fired 5 minutes apart with only (a)
   marked resolved -> open_events contains ONLY (b)'s event_id.
2. Full Traceability Drill-down: Each event ID allows drilling into its EventStory,
   Evidence, SOP, Guidance, and actions.
3. Zero State Mutation: Calling compile_handover multiple times with overlapping
   windows produces identical, side-effect-free results.
"""

import os
import uuid
import unittest
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from models import HandoverSummary, OperatorAction, EventStory, Evidence, SopMatch
from database import Database
from shift_handover import ShiftHandoverCompiler, compile_handover, get_event_drilldown
from operator_actions import OperatorActionAudit

# Full pipeline components
from generator import SyntheticDataGenerator
from stream import TagStream
from prioritizer import PrioritizationEngine
from dedup import DeduplicationEngine
from topology import TopologyGraph
from correlator import CorrelationEngine
from event_story import EventStoryConstructor
from evidence_engine import EvidenceEngine
from sop_retriever import SopRetriever
from guidance_generator import GuidanceGenerator


class TestShiftHandoverAcceptance(unittest.TestCase):
    """Component 10 Acceptance Tests."""

    def setUp(self):
        self.test_db_path = "test_handover_opslens.db"
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        self.db = Database(self.test_db_path)
        self.audit = OperatorActionAudit(db=self.db)
        self.compiler = ShiftHandoverCompiler(db=self.db)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_mixed_resolved_and_open_events_acceptance(self):
        """
        Acceptance Criterion:
        Compile a handover spanning scenarios (a) and (b) fired 5 minutes apart with
        only (a) marked resolved - verify open_events contains only (b)'s event_id.
        """
        stream = TagStream(db_path=self.test_db_path)
        prioritizer = PrioritizationEngine()
        dedup_engine = DeduplicationEngine(db=self.db, prioritizer=prioritizer)
        topology = TopologyGraph()
        correlator = CorrelationEngine(stream=stream, db=self.db, topology_graph=topology)
        story_constructor = EventStoryConstructor(db=self.db)
        evidence_engine = EvidenceEngine(db=self.db)
        sop_retriever = SopRetriever(db=self.db)
        guidance_gen = GuidanceGenerator(db=self.db)

        time_a = datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
        time_b = datetime(2026, 9, 11, 10, 5, 0, tzinfo=timezone.utc)

        generator = SyntheticDataGenerator(
            db=self.db,
            sample_interval=2.0,
            start_time=time_a
        )

        async def run_pipeline():
            # 1. Run Scenario A (Valve Restriction Cascade) at 10:00:00Z
            readings_a = list(generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
            for r in readings_a:
                dedup_engine.process_reading(r)

            candidates_a = self.db.get_candidate_events()
            self.assertEqual(len(candidates_a), 1)
            event_a_id = candidates_a[0].event_id

            correlated_a = await correlator.correlate_event(candidates_a[0])
            story_a = story_constructor.construct_story(correlated_a, persist=True)
            evidence_a = evidence_engine.evaluate_event(correlated_a, persist=True)
            sop_a = sop_retriever.retrieve(story=story_a, evidence=evidence_a, persist=True)
            guidance_gen.generate(story_a, evidence_a, sop_a)

            # 2. Run Scenario B (Bearing Wear Degradation) at 10:05:00Z (5 minutes later)
            generator.reset(clear_db=False, start_time=time_b)
            readings_b = list(generator.run_scenario("bearing_wear", speed_multiplier=float("inf")))
            for r in readings_b:
                dedup_engine.process_reading(r)

            all_candidates = self.db.get_candidate_events()
            self.assertEqual(len(all_candidates), 2)
            event_b_candidate = [c for c in all_candidates if c.event_id != event_a_id][0]
            event_b_id = event_b_candidate.event_id

            correlated_b = await correlator.correlate_event(event_b_candidate)
            story_b = story_constructor.construct_story(correlated_b, persist=True)
            evidence_b = evidence_engine.evaluate_event(correlated_b, persist=True)
            sop_b = sop_retriever.retrieve(story=story_b, evidence=evidence_b, persist=True)
            guidance_gen.generate(story_b, evidence_b, sop_b)

            # 3. Mark ONLY Event A as RESOLVED
            self.audit.log_action(
                event_id=event_a_id,
                operator="operator_smith",
                action_type="VERIFY",
                notes="Verified valve travel limit switch",
                timestamp="2026-09-11T10:02:00Z"
            )
            self.audit.log_action(
                event_id=event_a_id,
                operator="lead_operator_chen",
                action_type="RESOLVE",
                notes="Bypass valve adjusted, pressure normalized. Incident closed.",
                timestamp="2026-09-11T10:04:00Z"
            )

            # 4. Event B is ACKNOWLEDGED but NOT RESOLVED
            self.audit.log_action(
                event_id=event_b_id,
                operator="reliability_tech_ross",
                action_type="ACKNOWLEDGE",
                notes="Bearing vibration acknowledged, trending vibration.",
                timestamp="2026-09-11T10:07:00Z"
            )

            # 5. Compile Handover Summary spanning the shift
            shift_start = "2026-09-11T09:50:00Z"
            shift_end = "2026-09-11T10:30:00Z"

            summary = self.compiler.compile_handover(shift_start=shift_start, shift_end=shift_end)

            # Assertions:
            self.assertIsInstance(summary, HandoverSummary)
            self.assertEqual(summary.shift_start, shift_start)
            self.assertEqual(summary.shift_end, shift_end)

            # Both events must be in the events list
            self.assertIn(event_a_id, summary.events)
            self.assertIn(event_b_id, summary.events)
            self.assertEqual(len(summary.events), 2)

            # CRITICAL ACCEPTANCE CRITERION:
            # open_events must contain ONLY event B (event A was resolved)
            self.assertEqual(
                summary.open_events, [event_b_id],
                f"open_events violation: expected [{event_b_id}], got {summary.open_events}"
            )

            # Actions count must match logged actions in window
            self.assertEqual(len(summary.actions), 3)

            # 6. Test Traceability Drill-down
            drill_a = self.compiler.get_event_drilldown(event_a_id)
            self.assertEqual(drill_a["event_id"], event_a_id)
            self.assertIsNotNone(drill_a["story"])
            self.assertIsNotNone(drill_a["evidence"])
            self.assertIsNotNone(drill_a["sop_match"])
            self.assertIsNotNone(drill_a["guidance"])
            self.assertEqual(len(drill_a["actions"]), 2)

            drill_b = self.compiler.get_event_drilldown(event_b_id)
            self.assertEqual(drill_b["event_id"], event_b_id)
            self.assertEqual(len(drill_b["actions"]), 1)
            self.assertEqual(drill_b["actions"][0].action_type, "ACKNOWLEDGE")

            # 7. Test Repeated / Overlapping Calls (Zero State Mutation)
            # Query window covering only Event A
            sub_window_a = self.compiler.compile_handover("2026-09-11T09:55:00Z", "2026-09-11T10:03:00Z")
            self.assertIn(event_a_id, sub_window_a.events)
            self.assertNotIn(event_b_id, sub_window_a.events)
            self.assertEqual(sub_window_a.open_events, [])

            # Re-query full window: identical result
            summary_repeat = self.compiler.compile_handover(shift_start, shift_end)
            self.assertEqual(summary_repeat.events, summary.events)
            self.assertEqual(summary_repeat.open_events, summary.open_events)
            self.assertEqual(len(summary_repeat.actions), len(summary.actions))

        asyncio.run(run_pipeline())


if __name__ == "__main__":
    unittest.main()
