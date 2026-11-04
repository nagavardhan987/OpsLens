"""
OpsLens - Operator Action Audit Acceptance Verification (Component 9)

Verifies:
1. Overlapping Events Isolation: Actions logged for Event A never leak into Event B.
2. Cardinal Safety Constraint: Machine/PLC control commands are strictly rejected.
3. Orphan Action Prevention: Actions referencing non-existent events are rejected.
4. Open Events Lifecycle: Tracks open events until ACKNOWLEDGED or RESOLVED.
"""

import os
import uuid
import unittest
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from models import EventStory, EventStoryStep, OperatorAction
from database import Database
from operator_actions import OperatorActionAudit, ALLOWED_ACTION_TYPES

# Pipeline components for multi-scenario overlapping events test
from generator import SyntheticDataGenerator
from stream import TagStream
from prioritizer import PrioritizationEngine
from dedup import DeduplicationEngine
from topology import TopologyGraph
from correlator import CorrelationEngine
from event_story import EventStoryConstructor


class TestOperatorActionAudit(unittest.TestCase):
    """Component 9 Acceptance Tests."""

    def setUp(self):
        self.test_db_path = "test_audit_opslens.db"
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        self.db = Database(self.test_db_path)
        self.audit = OperatorActionAudit(db=self.db)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_overlapping_events_action_isolation(self):
        """
        Acceptance Criterion 1: Test with TWO overlapping events (fire scenario a and b
        close together) and verify actions logged against event A never appear when
        querying get_actions_for_event(event_id=B).
        """
        stream = TagStream(db_path=self.test_db_path)
        prioritizer = PrioritizationEngine()
        dedup_engine = DeduplicationEngine(db=self.db, prioritizer=prioritizer)
        topology = TopologyGraph()
        correlator = CorrelationEngine(stream=stream, db=self.db, topology_graph=topology)
        story_constructor = EventStoryConstructor(db=self.db)
        generator = SyntheticDataGenerator(
            db=self.db,
            sample_interval=2.0,
            start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
        )

        async def run_overlapping_pipeline():
            # 1. Fire Scenario A (Valve Restriction Cascade)
            readings_a = list(generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
            for r in readings_a:
                dedup_engine.process_reading(r)

            candidates_a = self.db.get_candidate_events()
            self.assertEqual(len(candidates_a), 1)
            event_a_id = candidates_a[0].event_id
            correlated_a = await correlator.correlate_event(candidates_a[0])
            story_constructor.construct_story(correlated_a, persist=True)

            # 2. Fire Scenario B (Bearing Degradation) close together
            generator.reset(clear_db=False, start_time=datetime(2026, 9, 11, 10, 5, 0, tzinfo=timezone.utc))
            readings_b = list(generator.run_scenario("bearing_wear", speed_multiplier=float("inf")))
            for r in readings_b:
                dedup_engine.process_reading(r)

            all_candidates = self.db.get_candidate_events()
            self.assertEqual(len(all_candidates), 2)
            event_b_candidate = [c for c in all_candidates if c.event_id != event_a_id][0]
            event_b_id = event_b_candidate.event_id
            correlated_b = await correlator.correlate_event(event_b_candidate)
            story_constructor.construct_story(correlated_b, persist=True)

            # Verify both stories exist in SQLite
            self.assertTrue(self.db.event_story_exists(event_a_id))
            self.assertTrue(self.db.event_story_exists(event_b_id))
            self.assertNotEqual(event_a_id, event_b_id)

            # 3. Log actions against Event A
            act_a1 = self.audit.log_action(
                event_id=event_a_id,
                operator="operator_j_smith",
                action_type="VERIFY",
                notes="Inspected physical valve stem position on VLV-04"
            )
            act_a2 = self.audit.log_action(
                event_id=event_a_id,
                operator="lead_operator_r_chen",
                action_type="ACKNOWLEDGE",
                notes="Throttling acknowledged. Initiating bypass procedure."
            )

            # 4. Strict Isolation Check: Event B MUST have 0 actions
            actions_b = self.audit.get_actions_for_event(event_id=event_b_id)
            self.assertEqual(
                len(actions_b), 0,
                f"Isolation breach: Event B contains actions logged for Event A! {actions_b}"
            )

            # Event A MUST have exactly 2 actions
            actions_a = self.audit.get_actions_for_event(event_id=event_a_id)
            self.assertEqual(len(actions_a), 2)
            self.assertEqual([a.action_id for a in actions_a], [act_a1.action_id, act_a2.action_id])
            self.assertEqual([a.action_type for a in actions_a], ["VERIFY", "ACKNOWLEDGE"])

            # 5. Log action against Event B and verify isolation in reverse
            act_b1 = self.audit.log_action(
                event_id=event_b_id,
                operator="reliability_tech_m_ross",
                action_type="ESCALATE",
                notes="Dispatched field team for handheld vibration check"
            )
            actions_b_after = self.audit.get_actions_for_event(event_id=event_b_id)
            self.assertEqual(len(actions_b_after), 1)
            self.assertEqual(actions_b_after[0].action_id, act_b1.action_id)

            # Event A still has exactly 2 actions
            actions_a_after = self.audit.get_actions_for_event(event_id=event_a_id)
            self.assertEqual(len(actions_a_after), 2)

        asyncio.run(run_overlapping_pipeline())

    def test_cardinal_safety_constraint_rejects_plc_commands(self):
        """
        Acceptance Criterion 2: Cardinal safety constraint: this layer must NEVER
        expose or accept any parameter representing a machine/PLC command - it only
        records human acknowledgment/decision strings.
        """
        # Create a valid event story in DB
        event_id = str(uuid.uuid4())
        story = EventStory(event_id=event_id, steps=[], causal_label="Pump High Pressure")
        self.db.save_event_story(story)

        # List of forbidden machine/PLC command strings
        forbidden_commands = [
            "SET_VALVE_POS",
            "SET_SPEED_RPM",
            "OVERRIDE_INTERLOCK",
            "START_PUMP",
            "STOP_COMPRESSOR",
            "TRIP_TURBINE",
            "SETPOINT_WRITE",
            "EMERGENCY_SHUTDOWN",
            "RESET_BREAKER",
            "PLC_FORCE_COIL",
            "WRITE_MODBUS_REGISTER",
            "OPEN_DISCHARGE_VALVE",
            "CLOSE_SUCTION_VALVE",
            "RANDOM_STRING_CMD"
        ]

        for cmd in forbidden_commands:
            with self.assertRaises(ValueError, msg=f"Safety violation: '{cmd}' was not rejected!"):
                self.audit.log_action(
                    event_id=event_id,
                    operator="rogue_agent",
                    action_type=cmd,
                    notes="Attempting machine control"
                )

        # Verify nothing was written to database
        actions = self.audit.get_actions_for_event(event_id)
        self.assertEqual(len(actions), 0)

        # Valid human decision action MUST succeed
        valid_action = self.audit.log_action(
            event_id=event_id,
            operator="authorized_operator",
            action_type="ACKNOWLEDGE",
            notes="Valid human acknowledgment"
        )
        self.assertEqual(valid_action.action_type, "ACKNOWLEDGE")
        actions_now = self.audit.get_actions_for_event(event_id)
        self.assertEqual(len(actions_now), 1)

    def test_orphan_event_prevention(self):
        """
        Requirement 1: Validates event_id exists in event_stories before writing
        (reject with a clear error if it doesn't - don't silently log orphaned actions).
        """
        fake_event_id = str(uuid.uuid4())
        self.assertFalse(self.db.event_story_exists(fake_event_id))

        with self.assertRaises(ValueError) as ctx:
            self.audit.log_action(
                event_id=fake_event_id,
                operator="operator_test",
                action_type="VERIFY",
                notes="Orphaned verification"
            )
        self.assertIn("does not exist in event_stories", str(ctx.exception))

        # Verify nothing was inserted in operator_actions
        self.assertEqual(len(self.db.get_operator_actions()), 0)

    def test_open_events_lifecycle_tracking(self):
        """
        Requirement 3: Expose get_open_events() (events in event_stories with no
        corresponding action of type 'RESOLVED' or 'ACKNOWLEDGED' yet).
        """
        event_1 = str(uuid.uuid4())
        event_2 = str(uuid.uuid4())

        self.db.save_event_story(EventStory(event_id=event_1, steps=[], causal_label="Event 1"))
        self.db.save_event_story(EventStory(event_id=event_2, steps=[], causal_label="Event 2"))

        # Initially, both events are open
        open_events = self.audit.get_open_events()
        self.assertIn(event_1, open_events)
        self.assertIn(event_2, open_events)
        self.assertEqual(len(open_events), 2)

        # Non-resolving action (VERIFY) does NOT close event_1
        self.audit.log_action(event_id=event_1, operator="op1", action_type="VERIFY")
        open_events = self.audit.get_open_events()
        self.assertIn(event_1, open_events)
        self.assertIn(event_2, open_events)

        # Non-resolving action (ESCALATE) does NOT close event_2
        self.audit.log_action(event_id=event_2, operator="op2", action_type="ESCALATE")
        open_events = self.audit.get_open_events()
        self.assertIn(event_1, open_events)
        self.assertIn(event_2, open_events)

        # ACKNOWLEDGE closes event_1
        self.audit.log_action(event_id=event_1, operator="op1", action_type="ACKNOWLEDGE")
        open_events = self.audit.get_open_events()
        self.assertNotIn(event_1, open_events)
        self.assertIn(event_2, open_events)
        self.assertEqual(len(open_events), 1)

        # RESOLVE closes event_2
        self.audit.log_action(event_id=event_2, operator="op2", action_type="RESOLVE")
        open_events = self.audit.get_open_events()
        self.assertNotIn(event_1, open_events)
        self.assertNotIn(event_2, open_events)
        self.assertEqual(len(open_events), 0)


if __name__ == "__main__":
    unittest.main()
