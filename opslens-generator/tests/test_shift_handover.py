"""
OpsLens - Unit Tests for Shift Handover Compiler (Component 10)
"""

import unittest
import uuid
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import EventStory, OperatorAction, HandoverSummary
from database import Database
from shift_handover import ShiftHandoverCompiler, compile_handover, get_event_drilldown
from operator_actions import OperatorActionAudit


class TestShiftHandoverUnit(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_handover_unit.db"
        self.db = Database(db_path=self.db_path)
        self.audit = OperatorActionAudit(db=self.db)
        self.compiler = ShiftHandoverCompiler(db=self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_window_validation_errors(self):
        """Verify invalid shift window raises ValueError."""
        with self.assertRaises(ValueError):
            self.compiler.compile_handover("", "2026-09-11T12:00:00Z")

        with self.assertRaises(ValueError):
            # start > end
            self.compiler.compile_handover("2026-09-11T14:00:00Z", "2026-09-11T10:00:00Z")

    def test_compile_handover_synthetic_unit(self):
        """Verify compilation logic and open_events calculation."""
        # Create 2 events directly in SQLite
        e1 = str(uuid.uuid4())
        e2 = str(uuid.uuid4())

        self.db.save_event_story(EventStory(
            event_id=e1,
            steps=[{"step_number": 1, "tag": "T1", "timestamp": "2026-09-11T08:15:00Z", "description": "d", "value_before": 0.0, "value_after": 1.0}],
            causal_label="Event 1"
        ))
        self.db.save_event_story(EventStory(
            event_id=e2,
            steps=[{"step_number": 1, "tag": "T2", "timestamp": "2026-09-11T08:45:00Z", "description": "d", "value_before": 0.0, "value_after": 1.0}],
            causal_label="Event 2"
        ))

        # Log RESOLVE for e1, ACKNOWLEDGE for e2
        self.audit.log_action(
            event_id=e1,
            operator="op1",
            action_type="RESOLVE",
            timestamp="2026-09-11T08:30:00Z"
        )
        self.audit.log_action(
            event_id=e2,
            operator="op2",
            action_type="ACKNOWLEDGE",
            timestamp="2026-09-11T08:50:00Z"
        )

        # Shift covers 08:00 to 09:00
        summary = self.compiler.compile_handover("2026-09-11T08:00:00Z", "2026-09-11T09:00:00Z")

        self.assertEqual(len(summary.events), 2)
        self.assertIn(e1, summary.events)
        self.assertIn(e2, summary.events)

        # e1 is resolved, so open_events contains only e2
        self.assertEqual(summary.open_events, [e2])
        self.assertEqual(len(summary.actions), 2)

    def test_drilldown_traceability_unit(self):
        """Verify drilldown returns dictionary with all component slots."""
        e1 = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=e1, steps=[], causal_label="E1"))
        self.audit.log_action(event_id=e1, operator="alice", action_type="VERIFY")

        drill = self.compiler.get_event_drilldown(e1)
        self.assertEqual(drill["event_id"], e1)
        self.assertIsNotNone(drill["story"])
        self.assertEqual(len(drill["actions"]), 1)


if __name__ == "__main__":
    unittest.main()
