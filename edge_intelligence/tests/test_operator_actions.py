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

from models import EventStory, IndividualAlarmRecord, OperatorAction
from database import Database
from operator_actions import OperatorActionAudit, log_action, get_actions_for_event, get_open_events, ALLOWED_ACTION_TYPES
from operational_history import build_handover_summary


class TestOperatorActionsUnit(unittest.TestCase):

    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        test_root.mkdir(exist_ok=True)
        self.temp_dir = tempfile.mkdtemp(dir=test_root)
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
        """Acknowledgement records operator awareness without closing an incident."""
        event_1 = str(uuid.uuid4())
        event_2 = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=event_1, steps=[], causal_label="E1"))
        self.db.save_event_story(EventStory(event_id=event_2, steps=[], causal_label="E2"))

        self.assertEqual(len(self.audit.get_open_events()), 2)
        self.audit.log_action(event_1, "alice", "ACKNOWLEDGE")
        self.assertEqual(set(self.audit.get_open_events()), {event_1, event_2})
        self.audit.log_action(event_1, "alice", "RESOLVE")
        self.assertEqual(self.audit.get_open_events(), [event_2])

    def test_log_event_uses_annotate_and_persists_operator_time_incident_and_note(self):
        event_id = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=event_id, steps=[], causal_label="Test incident"))
        action = self.audit.log_action(
            event_id=event_id, operator="operator-7", action_type="ANNOTATE",
            notes="Observed a repeated local indication.", timestamp="2026-10-31T12:00:00Z",
        )
        stored = self.audit.get_actions_for_event(event_id)[0]
        self.assertEqual(stored.action_type, "ANNOTATE")
        self.assertEqual(stored.operator, "operator-7")
        self.assertEqual(stored.timestamp, "2026-10-31T12:00:00Z")
        self.assertEqual(stored.event_id, event_id)
        self.assertEqual(stored.notes, "Observed a repeated local indication.")
        self.assertEqual(action.action_id, stored.action_id)
        self.assertEqual(self.db.get_event_status(event_id), "OPEN")

    def test_verify_and_inspect_are_independent_audit_actions(self):
        event_id = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=event_id, steps=[], causal_label="Test incident"))
        self.audit.log_action(event_id, "operator-7", "VERIFY", "Verified display only.")
        self.audit.log_action(event_id, "operator-7", "INSPECT", "Inspection acknowledged.")
        self.assertEqual([a.action_type for a in self.audit.get_actions_for_event(event_id)], ["VERIFY", "INSPECT"])
        self.assertEqual(self.db.get_event_status(event_id), "OPEN")
        self.assertIn(event_id, self.audit.get_open_events())

    def test_mark_unresolved_sets_latest_status_and_keeps_incident_open(self):
        event_id = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=event_id, steps=[], causal_label="Test incident"))
        self.audit.log_action(event_id, "operator-7", "MARK_UNRESOLVED", "Awaiting maintenance review.")
        self.assertEqual(self.db.get_event_status(event_id), "UNRESOLVED")
        self.assertFalse(self.db.is_event_resolved(event_id))
        self.assertIn(event_id, self.audit.get_open_events())
        self.assertEqual(self.audit.get_actions_for_event(event_id)[0].notes, "Awaiting maintenance review.")

    def test_alarm_acknowledgement_is_persistent_active_and_idempotent(self):
        event_id = str(uuid.uuid4())
        alarm_id = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=event_id, steps=[], causal_label="Active alarm"))
        alarm = IndividualAlarmRecord(
            alarm_id=alarm_id, source_event_id=event_id, tag="ALM-P02-HP", equipment_id="Pump-02",
            value=True, first_seen_timestamp="2026-11-03T10:00:00Z", last_seen_timestamp="2026-11-03T10:00:00Z",
        )
        self.db.save_individual_alarm(event_id, alarm)

        action, created = self.db.record_alarm_acknowledgement(
            event_id, alarm_id, "operator-7", "OpsLens acknowledgement.", "2026-11-03T10:05:00Z",
        )
        self.assertTrue(created)
        self.assertEqual(action.action_type, "ACKNOWLEDGE")
        saved_alarm = self.db.get_individual_alarms(event_id)[0]
        self.assertEqual(saved_alarm["lifecycle_state"], "ACKNOWLEDGED")
        self.assertEqual(saved_alarm["acknowledged_timestamp"], "2026-11-03T10:05:00Z")
        self.assertEqual(self.db.get_alarm_transitions(alarm_id)[-1]["state"], "ACKNOWLEDGED")
        self.assertEqual(self.db.get_event_status(event_id), "ACKNOWLEDGED")
        self.assertIn(event_id, self.audit.get_open_events())
        handover = build_handover_summary(self.db, "2026-11-03T10:00:00Z", "2026-11-03T11:00:00Z")
        self.assertEqual(handover["unacknowledged_alarms"], [])
        self.assertEqual(handover["open_alarms"][0]["status"], "ACKNOWLEDGED")
        self.assertEqual(handover["alarms_acknowledged_in_shift"][0]["alarm_id"], "ALM-P02-HP")

        repeated, created_again = self.db.record_alarm_acknowledgement(
            event_id, alarm_id, "operator-7", "Duplicate click.", "2026-11-03T10:06:00Z",
        )
        self.assertFalse(created_again)
        self.assertEqual(repeated.action_id, action.action_id)
        self.assertEqual(len(self.db.get_operator_actions(event_id)), 1)
        self.assertEqual(len(self.db.get_alarm_transitions(alarm_id)), 1)

        # A repeated active telemetry sample must not erase the recorded acknowledgement.
        alarm.last_seen_timestamp = "2026-11-03T10:07:00Z"
        alarm.repeat_count = 2
        self.db.save_individual_alarm(event_id, alarm)
        self.assertEqual(self.db.get_individual_alarms(event_id)[0]["lifecycle_state"], "ACKNOWLEDGED")

    def test_latest_resolution_requires_new_unresolved_transition_to_reopen(self):
        event_id = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=event_id, steps=[], causal_label="Test incident"))
        self.audit.log_action(event_id, "operator-7", "RESOLVE", "Operator confirmed clear.", "2026-10-31T12:00:00Z")
        self.assertEqual(self.db.get_event_status(event_id), "RESOLVED")
        self.assertNotIn(event_id, self.audit.get_open_events())
        self.audit.log_action(event_id, "operator-7", "MARK_UNRESOLVED", "Alarm recurred.", "2026-10-31T12:01:00Z")
        self.assertEqual(self.db.get_event_status(event_id), "UNRESOLVED")
        self.assertIn(event_id, self.audit.get_open_events())


if __name__ == "__main__":
    unittest.main()
