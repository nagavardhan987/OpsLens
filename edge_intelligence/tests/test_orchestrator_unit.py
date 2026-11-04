"""
OpsLens - Unit Tests for Live Pipeline Orchestrator & API (Component 11)
"""

import unittest
import uuid
import sys
import tempfile
import shutil
from unittest.mock import AsyncMock, Mock
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import CandidateEvent, CorrelatedEvent, CorrelatedDeviation, EventStory, IndividualAlarmRecord, OperatorAction, TagReading, SopMatch, Guidance
from database import Database
from orchestrator import OpsLensOrchestrator
from api.routes import create_app
from alarm_priority import AlarmPriorityInterpreter


class TestOrchestratorUnit(unittest.TestCase):

    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        test_root.mkdir(exist_ok=True)
        self.temp_dir = tempfile.mkdtemp(dir=test_root)
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

    def test_sop_and_guidance_failures_do_not_erase_incident_evidence(self):
        event_id = str(uuid.uuid4())
        alarm_time = "2026-10-29T04:44:38.052481Z"
        sequence_time = "2026-10-29T04:43:48.052481Z"
        candidate = CandidateEvent(
            event_id=event_id, primary_tag="ALM-SCR-110-DL", primary_alarm=True,
            trigger_timestamp=alarm_time, raw_deviation_pct=100.0,
            clustered_tags=["LDT-110-SCR", "ALM-SCR-110-DL"],
        )
        correlated = CorrelatedEvent(
            **candidate.model_dump(),
            correlated_deviations=[CorrelatedDeviation(
                tag="LDT-110-SCR", deviation_pct=380.0,
                timestamp=sequence_time, precedes_primary=True, topology_distance=1,
            )],
        )

        async def persist_correlated(_candidate, **_kwargs):
            self.db.save_correlated_event(correlated, equipment_id="InletWorks-01")
            return correlated

        self.orchestrator.correlator.correlate_event = AsyncMock(side_effect=persist_correlated)
        self.orchestrator.sop_retriever.retrieve = Mock(side_effect=RuntimeError("index unavailable"))
        self.orchestrator.guidance_generator.generate = Mock(side_effect=RuntimeError("guidance unavailable"))
        self.orchestrator.alarm_synthesis.synthesize = Mock(return_value={})

        pipeline = self.orchestrator.process_candidate_event(candidate)
        try:
            pipeline.send(None)
        except StopIteration as completed:
            result = completed.value
        else:
            pipeline.close()
            self.fail("The mocked event pipeline unexpectedly suspended on external async work.")

        self.assertEqual(result["event_id"], event_id)
        self.assertIsNotNone(result["story"])
        self.assertEqual(result["evidence"]["likely_contributor_tag"], "LDT-110-SCR")
        self.assertEqual(result["sop_match"]["retrieval_status"], "unavailable")
        self.assertEqual(result["sop_match"]["retrieved_chunks"], [])
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

    def test_api_acknowledge_alarm_persists_status_and_rejects_duplicate_click(self):
        event_id = str(uuid.uuid4())
        alarm_id = str(uuid.uuid4())
        self.db.save_event_story(EventStory(event_id=event_id, steps=[], causal_label="Active pressure alarm"))
        self.db.save_individual_alarm(event_id, IndividualAlarmRecord(
            alarm_id=alarm_id, source_event_id=event_id, tag="ALM-P02-HP", equipment_id="Pump-02",
            value=True, first_seen_timestamp="2026-11-03T10:00:00Z", last_seen_timestamp="2026-11-03T10:00:00Z",
        ))
        payload = {
            "event_id": event_id, "alarm_id": alarm_id, "operator": "Demo Operator",
            "action_type": "ACKNOWLEDGE", "notes": "Reviewed active pressure alarm.",
            "timestamp": "2026-11-03T10:05:00Z",
        }
        failed = self.client.post("/api/actions", json={**payload, "alarm_id": "not-linked"})
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(self.db.get_operator_actions(event_id), [])
        first = self.client.post("/api/actions", json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(first.json()["already_acknowledged"])
        self.assertEqual(first.json()["alarm_state"], "ACTIVE — ACKNOWLEDGED")
        self.assertFalse(first.json()["writes_to_plc"])

        repeated = self.client.post("/api/actions", json=payload)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertTrue(repeated.json()["already_acknowledged"])
        self.assertEqual(len(self.db.get_operator_actions(event_id)), 1)
        alarm = self.db.get_individual_alarms(event_id)[0]
        self.assertEqual(alarm["lifecycle_state"], "ACKNOWLEDGED")
        self.assertIsNone(alarm["cleared_timestamp"])
        self.assertEqual(len(self.db.get_alarm_transitions(alarm_id)), 1)
        self.assertIn(event_id, self.db.get_open_event_ids())
        history = self.client.get("/api/alarms/history", params={"incident_id": event_id}).json()
        self.assertEqual(history["alarms"][0]["status"], "ACKNOWLEDGED")
        self.assertEqual(history["alarms"][0]["acknowledged_by"], "Demo Operator")

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

    def _save_high_pressure_story(self, event_id, alarm_time="2026-10-01T10:00:00Z"):
        self.db.save_event_story(EventStory(
            event_id=event_id,
            steps=[{"step_number": 1, "tag": "ALM-P02-HP", "timestamp": alarm_time,
                    "description": "High pressure alarm active", "value_before": False, "value_after": True}],
            causal_label="Pump-02 high pressure"
        ))

    def test_active_alarm_input_cannot_be_resolved(self):
        event_id = str(uuid.uuid4())
        self._save_high_pressure_story(event_id)
        self.db.insert_reading(TagReading(
            tag="ALM-P02-HP", value=True, timestamp="2026-10-01T10:00:02Z",
            unit="status", equipment_id="Pump-02"
        ))
        response = self.client.post("/api/actions", json={
            "event_id": event_id, "operator": "test", "action_type": "RESOLVE"
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.db.is_event_resolved(event_id))

    def test_stale_clear_timestamp_with_later_wall_clock_text_cannot_resolve(self):
        event_id = str(uuid.uuid4())
        self._save_high_pressure_story(event_id)
        # 10:30 at UTC+1 is 09:30Z, so this is older than the 10:00Z alarm
        # despite its lexicographically later timestamp string.
        stale = TagReading(
            tag="ALM-P02-HP", value=False, timestamp="2026-10-01T10:30:00+01:00",
            unit="status", equipment_id="Pump-02"
        )
        self.db.insert_reading(stale)
        latest = self.db.get_latest_reading("ALM-P02-HP")
        self.assertEqual(latest.timestamp, stale.timestamp)
        state = self.client.get(f"/api/events/{event_id}").json()["runtime_alarm_state"]
        self.assertFalse(state["is_later_than_alarm"])
        response = self.client.post("/api/actions", json={
            "event_id": event_id, "operator": "test", "action_type": "RESOLVE"
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.db.is_event_resolved(event_id))

    def test_subsequent_clear_sample_enables_operator_confirmation_and_resolution(self):
        event_id = str(uuid.uuid4())
        self._save_high_pressure_story(event_id)
        self.db.insert_reading(TagReading(
            tag="ALM-P02-HP", value=True, timestamp="2026-10-01T10:00:01Z",
            unit="status", equipment_id="Pump-02"
        ))
        self.db.insert_reading(TagReading(
            tag="ALM-P02-HP", value=False, timestamp="2026-10-01T12:00:02+02:00",
            unit="status", equipment_id="Pump-02"
        ))
        state = self.client.get(f"/api/events/{event_id}").json()["runtime_alarm_state"]
        self.assertFalse(state["active"])
        self.assertTrue(state["is_later_than_alarm"])
        response = self.client.post("/api/actions", json={
            "event_id": event_id, "operator": "test", "action_type": "RESOLVE"
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.db.is_event_resolved(event_id))
        full = self.client.get(f"/api/events/{event_id}").json()
        self.assertTrue(any(action["action_type"] == "RESOLVE" for action in full["actions"]))

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
