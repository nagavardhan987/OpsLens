import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from api.routes import create_app
from context_builder import ContextBuilder, ContextEventNotFound, InvalidContextTimestamp, parse_timestamp
from database import Database
from models import CandidateEvent, EventStory, OperatorAction, TagReading
from fastapi.testclient import TestClient


REFERENCE = "2026-10-16T10:00:00Z"
EVENT_ID = "context-event"


def event_record(event_id=EVENT_ID):
    return {
        "event_id": event_id,
        "trigger_timestamp": REFERENCE,
        "status": "OPEN",
        "candidate": {
            "event_id": event_id,
            "primary_tag": "ALM-P02-HP",
            "primary_alarm": True,
            "alarm_severity": "HIGH",
            "trigger_timestamp": REFERENCE,
            "raw_deviation_pct": 43.0,
            "clustered_tags": ["ALM-P02-HP", "PIT-02-PRS"],
        },
        "correlated": {"equipment_id": "Pump-02"},
        "story": {"causal_label": "Pressure excursion", "steps": [
            {"step_number": 1, "tag": "ALM-P02-HP", "timestamp": REFERENCE,
             "description": "High pressure alarm", "value_before": 0, "value_after": 1}
        ]},
        "evidence": {"likely_contributor_tag": "PIT-02-PRS", "confidence_score": 0.7},
        "evidence_audit": None,
        "sop_match": {"sop_id": "SOP-1", "sop_title": "Pump procedure",
                      "retrieval_method": "qdrant_vector_search",
                      "retrieved_chunks": [{"text": "Check pressure trend.", "section": "Checks",
                                            "page": 2, "similarity_score": 0.71,
                                            "payload": {"document_name": "pump.pdf", "sop_id": "SOP-1",
                                                        "title": "Pump procedure", "revision": "2"}}]},
    }


class TestContextBuilder(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db = Database(Path(self.temp_dir) / "context.db")
        self.event = event_record()
        self.builder = ContextBuilder(self.db, lambda event_id: self.event if event_id == EVENT_ID else None)
        self.db.save_candidate_event(CandidateEvent(**self.event["candidate"]), "Pump-02")
        self.db.save_event_story(EventStory(
            event_id=EVENT_ID, steps=self.event["story"]["steps"], causal_label="Pressure excursion"
        ))

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def add_reading(self, tag, value, timestamp, equipment="Pump-02", unit=""):
        self.db.insert_reading(TagReading(
            tag=tag, value=value, timestamp=timestamp, unit=unit, equipment_id=equipment
        ))

    def add_action(self, action_id, timestamp, event_id=EVENT_ID, action="ACKNOWLEDGE"):
        self.db.save_operator_action(OperatorAction(
            action_id=action_id, event_id=event_id, operator="operator", action_type=action,
            timestamp=timestamp, notes=None,
        ))

    def test_inclusive_thirty_minute_boundaries_and_outside_reading(self):
        self.add_reading("FIT-02-FLW", 70, "2026-10-16T09:30:00Z")
        self.add_reading("PIT-02-PRS", 6.5, "2026-10-16T10:00:00Z")
        self.add_reading("PIT-02-PRS", 6.6, "2026-10-16T09:29:59.999Z")
        context = self.builder.build(EVENT_ID)
        self.assertEqual(context.window.start, "2026-10-16T09:30:00Z")
        self.assertEqual(context.window.end, REFERENCE)
        self.assertEqual([r.timestamp for r in context.readings], [
            "2026-10-16T09:30:00Z", "2026-10-16T10:00:00Z"
        ])

    def test_chronological_order_and_unrelated_equipment_and_tag_excluded(self):
        self.add_reading("MOT-02-CUR", 9, "2026-10-16T09:55:00Z")
        self.add_reading("FIT-02-FLW", 60, "2026-10-16T09:45:00Z")
        self.add_reading("CMP-01-VIB", 8, "2026-10-16T09:50:00Z", equipment="Compressor-01")
        self.add_reading("CMP-01-VIB", 8, "2026-10-16T09:51:00Z", equipment="Pump-02")
        context = self.builder.build(EVENT_ID)
        self.assertEqual([r.tag for r in context.readings], ["FIT-02-FLW", "MOT-02-CUR"])
        self.assertTrue(all(r.equipment_id == "Pump-02" for r in context.readings))

    def test_related_events_status_and_operator_actions_are_windowed(self):
        related_id = "related-event"
        self.db.save_candidate_event(CandidateEvent(
            event_id=related_id, primary_tag="PIT-02-PRS", primary_alarm=True,
            trigger_timestamp="2026-10-16T09:30:00Z", raw_deviation_pct=20,
            clustered_tags=["PIT-02-PRS"], alarm_severity="WARNING",
        ), "Pump-02")
        self.db.save_event_story(EventStory(event_id=related_id, steps=[], causal_label="Related pressure event"))
        self.add_action("in-window", "2026-10-16T09:50:00Z")
        self.add_action("start-boundary", "2026-10-16T09:30:00Z")
        self.add_action("end-boundary", "2026-10-16T10:00:00Z")
        self.add_action("before-window", "2026-10-16T09:29:59Z")
        self.add_action("after-reference", "2026-10-16T10:00:01Z")
        self.add_action("related-ack", "2026-10-16T09:45:00Z", related_id)
        context = self.builder.build(EVENT_ID)
        self.assertEqual([e.event_id for e in context.related_events], [related_id])
        self.assertEqual(context.related_events[0].status, "ACKNOWLEDGED")
        self.assertEqual({a.action_id for a in context.operator_actions}, {
            "in-window", "start-boundary", "end-boundary", "related-ack"
        })

    def test_empty_history_is_explicit_and_not_fabricated(self):
        context = self.builder.build(EVENT_ID)
        self.assertEqual(context.readings, [])
        self.assertTrue(context.trend_summaries)
        self.assertTrue(all(item["reading_count"] == 0 for item in context.trend_summaries))
        self.assertEqual(context.operator_actions, [])
        self.assertTrue(any("No relevant timestamped" in item for item in context.missing_data))
        self.assertIsNone(context.selected_event.alarm_state)

    def test_alarm_reading_uses_store_provenance_not_nonexistent_model_source(self):
        self.add_reading("ALM-P02-HP", True, REFERENCE, unit="bool")
        context = self.builder.build(EVENT_ID)

        self.assertEqual(context.selected_event.alarm_state["tag"], "ALM-P02-HP")
        self.assertIs(context.selected_event.alarm_state["value"], True)
        self.assertEqual(context.selected_event.alarm_state["source"], "sqlite.tag_readings")

    def test_unknown_event_and_invalid_reference_timestamp(self):
        with self.assertRaises(ContextEventNotFound):
            self.builder.build("does-not-exist")
        with self.assertRaises(InvalidContextTimestamp):
            self.builder.build(EVENT_ID, "not-a-timestamp")

    def test_identical_duplicate_records_removed_but_distinct_values_kept(self):
        timestamp = "2026-10-16T09:50:00Z"
        self.add_reading("FIT-02-FLW", 60, timestamp, unit="L/min")
        self.add_reading("FIT-02-FLW", 60, timestamp, unit="L/min")
        self.add_reading("FIT-02-FLW", 61, timestamp, unit="L/min")
        context = self.builder.build(EVENT_ID)
        self.assertEqual(context.duplicate_readings_removed, 1)
        self.assertEqual([r.value for r in context.readings], [60, 61])

    def test_offset_and_naive_timestamps_are_normalized_as_utc(self):
        local_ref = "2026-10-16T15:30:00+05:30"
        self.add_reading("FIT-02-FLW", 64, "2026-10-16T15:00:00+05:30")
        context = self.builder.build(EVENT_ID, local_ref)
        self.assertEqual(context.reference_timestamp, REFERENCE)
        self.assertEqual(context.window.start, "2026-10-16T09:30:00Z")
        self.assertEqual(context.readings[0].timestamp_utc, "2026-10-16T09:30:00Z")
        flow_trend = next(item for item in context.trend_summaries if item["tag"] == "FIT-02-FLW")
        self.assertEqual(flow_trend["first_observed"]["value"], 64)
        self.assertEqual(parse_timestamp("2026-10-16T10:00:00"), datetime(2026, 10, 16, 10, tzinfo=timezone.utc))

    def test_sop_references_and_hypothesis_are_preserved_and_labeled(self):
        context = self.builder.build(EVENT_ID)
        self.assertEqual(context.incident_analysis.matched_sop["references"][0]["document_name"], "pump.pdf")
        self.assertIn("not confirmed physical causation", context.hypotheses[0])

    def test_candidate_and_event_story_alarm_timestamps_keep_their_sources(self):
        story_timestamp = "2026-10-16T09:59:21Z"
        self.event["story"]["steps"][0]["timestamp"] = story_timestamp
        context = self.builder.build(EVENT_ID)
        selected = context.selected_event
        self.assertEqual(selected.timestamp, REFERENCE)
        self.assertEqual(selected.timestamp_source, "candidate_events.trigger_timestamp")
        self.assertEqual(selected.event_story_alarm_timestamp, story_timestamp)
        self.assertTrue(selected.timestamp_discrepancy)
        self.assertTrue(any("candidate event trigger timestamp and event-story alarm-step timestamp differ" in note
                            for note in context.missing_data))


class TestContextBuilderAPI(unittest.TestCase):
    class FakeDatabase:
        def get_context_readings(self, **_kwargs):
            return [{
                "record_id": 1, "tag": "ALM-P02-HP", "value": True,
                "timestamp": REFERENCE, "unit": "bool", "equipment_id": "Pump-02",
            }]
        def get_context_events(self, **_kwargs): return []
        def get_context_actions(self, *_args): return []
        def get_latest_reading(self, tag):
            return TagReading(tag=tag, value=True, timestamp=REFERENCE,
                              unit="bool", equipment_id="Pump-02")
        def get_conversation_event_id(self, _conversation_id): return None
        def get_assistant_messages(self, *_args, **_kwargs): return []
        def save_assistant_message(self, *_args, **_kwargs): return None
        def get_similar_incidents(self, **_kwargs): return []

    class FakeOrchestrator:
        def __init__(self):
            self.db = TestContextBuilderAPI.FakeDatabase()

        def get_full_event(self, event_id):
            return event_record(event_id) if event_id == EVENT_ID else None

    def test_context_preview_api_and_assistant_integration(self):
        import assistant
        assistant._llm_complete_override = lambda _prompt: '{"answer":"Deterministic test response"}'
        try:
            client = TestClient(create_app(orchestrator=self.FakeOrchestrator()))
            response = client.get(f"/api/events/{EVENT_ID}/context")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["window"]["duration_minutes"], 30)
            assistant_response = client.post("/api/assistant/ask", json={
                "event_id": EVENT_ID, "question": "Why did this alarm trigger?"
            })
            self.assertEqual(assistant_response.status_code, 200)
            self.assertEqual(
                assistant_response.json()["context"]["selected_event"]["alarm_state"]["source"],
                "sqlite.tag_readings",
            )
            self.assertEqual(client.get("/api/events/missing/context").status_code, 404)
            invalid = client.get(f"/api/events/{EVENT_ID}/context?reference_timestamp=invalid")
            self.assertEqual(invalid.status_code, 422)
        finally:
            assistant._llm_complete_override = None


if __name__ == "__main__":
    unittest.main()
