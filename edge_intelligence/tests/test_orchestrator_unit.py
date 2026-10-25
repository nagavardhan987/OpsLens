"""
OpsLens - Unit Tests for Live Pipeline Orchestrator & API (Component 11)
"""

import unittest
import uuid
import sys
import tempfile
import shutil
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import CandidateEvent, EventStory, OperatorAction, TagReading, SopMatch, Guidance
from database import Database
from orchestrator import OpsLensOrchestrator
from api.routes import create_app
from alarm_priority import AlarmPriorityInterpreter


class TestOrchestratorUnit(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_orch_unit.db"
        self.db = Database(db_path=self.db_path)
        self.orchestrator = OpsLensOrchestrator(db=self.db)
        self.app = create_app(orchestrator=self.orchestrator)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_full_event_not_found(self):
        """Verify non-existent event returns None and 404 in API."""
        non_existent = str(uuid.uuid4())
        self.assertIsNone(self.orchestrator.get_full_event(non_existent))
        resp = self.client.get(f"/api/events/{non_existent}")
        self.assertEqual(resp.status_code, 404)

    def test_get_full_event_joined_structure(self):
        """Verify get_full_event cross-table join structure."""
        event_id = str(uuid.uuid4())
        self.db.save_candidate_event(
            CandidateEvent(
                event_id=event_id,
                primary_tag="VLV-04-POS",
                primary_alarm=True,
                trigger_timestamp="2026-09-11T10:00:00Z",
                raw_deviation_pct=-44.9,
                clustered_tags=["VLV-04-POS"]
            ),
            equipment_id="Pump-02"
        )
        self.db.save_event_story(
            EventStory(
                event_id=event_id,
                steps=[{"step_number": 1, "tag": "VLV-04-POS", "timestamp": "2026-09-11T10:00:00Z", "description": "d", "value_before": 100.0, "value_after": 55.1}],
                causal_label="Valve Throttling"
            )
        )

        full = self.orchestrator.get_full_event(event_id)
        self.assertIsNotNone(full)
        self.assertEqual(full["event_id"], event_id)
        self.assertEqual(full["primary_tag"], "VLV-04-POS")
        self.assertEqual(full["status"], "OPEN")
        self.assertTrue(full["is_open"])
        self.assertIsNotNone(full["candidate"])
        self.assertIsNotNone(full["story"])

    def test_get_full_event_hides_cached_sop_and_guidance_for_wrong_equipment(self):
        event_id = str(uuid.uuid4())
        self.db.save_candidate_event(
            CandidateEvent(
                event_id=event_id,
                primary_tag="TNK-01-LVL",
                primary_alarm=True,
                trigger_timestamp="2026-10-19T06:55:16Z",
                raw_deviation_pct=48.0,
                clustered_tags=["TNK-01-LVL"],
            ),
            equipment_id="Tank-01",
        )
        self.db.save_sop_match(SopMatch(
            event_id=event_id,
            sop_id="SOP-P02-SEAL-01",
            sop_title="Pump-02 Mechanical Seal Leak",
            match_score=3.5,
            steps=["Pump-specific step"],
            source="bm25",
            why_retrieved={"equipment": "Pump-02"},
        ))
        self.db.save_guidance(Guidance(
            event_id=event_id,
            explanation_text="Pump-specific guidance",
            next_best_actions=["Pump-specific action"],
            cited_sop_id="SOP-P02-SEAL-01",
        ))

        result = self.orchestrator.get_full_event(event_id)
        self.assertIsNone(result["sop_match"])
        self.assertIsNone(result["guidance"])

    def test_api_log_action_and_open_events(self):
        """Verify API route for logging actions and checking open events."""
        event_id = str(uuid.uuid4())
        self.db.save_event_story(
            EventStory(event_id=event_id, steps=[], causal_label="Story")
        )

        # Initially open
        resp_open = self.client.get("/api/events/open")
        self.assertIn(event_id, resp_open.json()["open_events"])

        # Log ACKNOWLEDGE action
        resp_act = self.client.post("/api/actions", json={
            "event_id": event_id,
            "operator": "test_op",
            "action_type": "ACKNOWLEDGE",
            "notes": "Acked"
        })
        self.assertEqual(resp_act.status_code, 200)

        # Safety rejection on PLC command
        resp_fail = self.client.post("/api/actions", json={
            "event_id": event_id,
            "operator": "bad_actor",
            "action_type": "START_MOTOR"
        })
        self.assertEqual(resp_fail.status_code, 400)

    def test_resolution_requires_later_clear_alarm_reading(self):
        """An operator cannot resolve an incident until a later source value is clear."""
        event_id = str(uuid.uuid4())
        alarm_time = "2026-10-01T10:00:00Z"
        self.db.save_event_story(EventStory(
            event_id=event_id,
            steps=[{"step_number": 1, "tag": "ALM-P02-HP", "timestamp": alarm_time,
                    "description": "High pressure alarm active", "value_before": 0.0, "value_after": 1.0}],
            causal_label="Pump-02 high pressure"
        ))
        blocked = self.client.post("/api/actions", json={
            "event_id": event_id, "operator": "test", "action_type": "RESOLVE"
        })
        self.assertEqual(blocked.status_code, 400)

        self.db.insert_reading(TagReading(
            tag="ALM-P02-HP", value=False, timestamp="2026-10-01T10:00:02Z",
            unit="status", equipment_id="Pump-02"
        ))
        accepted = self.client.post("/api/actions", json={
            "event_id": event_id, "operator": "test", "action_type": "RESOLVE"
        })
        self.assertEqual(accepted.status_code, 200)

    def test_alarm_priority_interpreter_never_overrides_source_severity(self):
        result = AlarmPriorityInterpreter.interpret("Critical", related_signal_count=3)
        self.assertEqual(result["display_priority"], "Critical")
        self.assertEqual(result["priority_basis"], "configured source priority")
        self.assertFalse(result["priority_overridden"])
        missing = AlarmPriorityInterpreter.interpret(None, related_signal_count=2)
        self.assertEqual(missing["display_priority"], "not supplied")
        self.assertEqual(missing["priority_basis"], "not supplied by source")


if __name__ == "__main__":
    unittest.main()
