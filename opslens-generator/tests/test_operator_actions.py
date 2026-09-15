"""
OpsLens - Unit Tests for Operator Action Audit Layer (Component 9)
"""

import unittest
import uuid
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import EventStory, OperatorAction
from database import Database
from operator_actions import OperatorActionAudit, log_action, get_actions_for_event, get_open_events, ALLOWED_ACTION_TYPES


class TestOperatorActionsUnit(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_audit_unit.db"
        self.db = Database(db_path=self.db_path)
        self.audit = OperatorActionAudit(db=self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_log_action_success_and_query(self):
        """Verify normal action logging and querying."""
        event_id = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=event_id, steps=[], causal_label="Valve Flow Drop"))

        action = self.audit.log_action(
            event_id=event_id,
            operator="alice",
            action_type="VERIFY",
            notes="Checked bypass valve"
        )
        self.assertIsInstance(action, OperatorAction)
        self.assertEqual(action.event_id, event_id)
        self.assertEqual(action.operator, "alice")
        self.assertEqual(action.action_type, "VERIFY")
        self.assertEqual(action.notes, "Checked bypass valve")

        actions = self.audit.get_actions_for_event(event_id)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action_id, action.action_id)

    def test_safety_allowlist_enforcement(self):
        """Verify that PLC commands and unlisted strings raise ValueError."""
        event_id = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=event_id, steps=[], causal_label="Compressor High Temp"))

        unsafe_cmds = ["SET_VALVE_POS", "START_PUMP", "SHUTDOWN", "FORCE_COIL"]
        for cmd in unsafe_cmds:
            with self.assertRaises(ValueError):
                self.audit.log_action(event_id, "bad_actor", cmd)

    def test_orphan_event_rejection(self):
        """Verify non-existent event_id raises ValueError."""
        with self.assertRaises(ValueError):
            self.audit.log_action(str(uuid.uuid4()), "alice", "ACKNOWLEDGE")

    def test_open_events_query(self):
        """Verify get_open_events returns only unhandled events."""
        event_1 = str(uuid.uuid4())
        event_2 = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=event_1, steps=[], causal_label="E1"))
        self.db.save_event_story(EventStory(event_id=event_2, steps=[], causal_label="E2"))

        self.assertEqual(len(self.audit.get_open_events()), 2)
        self.audit.log_action(event_1, "alice", "ACKNOWLEDGE")
        self.assertEqual(self.audit.get_open_events(), [event_2])


if __name__ == "__main__":
    unittest.main()
