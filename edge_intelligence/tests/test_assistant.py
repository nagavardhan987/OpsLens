import unittest
from fastapi.testclient import TestClient

from assistant import build_assistant_response
from api.routes import create_app
from trend_analysis import summarize_readings


def example_event():
    return {
        "event_id": "incident-1",
        "trigger_timestamp": "2026-10-16T10:00:00Z",
        "candidate": {"primary_tag": "PIT-02-PRS", "primary_alarm": True, "alarm_severity": "HIGH", "trigger_timestamp": "2026-10-16T10:00:00Z"},
        "story": {"causal_label": "Flow reduction followed by pressure rise", "steps": [
            {"tag": "FIT-02-FLW", "timestamp": "2026-10-16T09:59:00Z", "description": "Flow decreased", "value_before": 82, "value_after": 56},
            {"tag": "ALM-P02-HP", "timestamp": "2026-10-16T10:00:00Z", "description": "High pressure alarm", "value_before": 0, "value_after": 1},
        ]},
        "evidence": {"likely_contributor_tag": "FIT-02-FLW", "confidence_score": 0.69},
        "evidence_audit": {"scoring_breakdown": {"tag_scores": {"FIT-02-FLW": {"deviation_pct": -31.7, "observed_reading": {"value": 56, "unit": "L/min", "timestamp": "2026-10-16T09:59:00Z"}}}}},
        "sop_match": {"sop_id": "SOP-DEMO-1", "sop_title": "Demo procedure", "retrieved_chunks": [{"text": "Check the documented flow trend.", "payload": {"document_name": "pump_manual.pdf", "section": "Flow checks", "page": 4, "document_status": "Fictional demo; not approved"}}]},
        "runtime_alarm_state": {"tag": "ALM-P02-HP", "active": True, "observed": True, "timestamp": "2026-10-16T10:00:01Z"},
    }


class FakeDatabase:
    def __init__(self):
        self.messages = []

    def get_latest_reading(self, _tag):
        return None

    def get_context_readings(self, **_kwargs):
        return []

    def get_context_events(self, **_kwargs):
        return []

    def get_context_actions(self, *_args):
        return []

    def get_conversation_event_id(self, conversation_id):
        for item in self.messages:
            if item["conversation_id"] == conversation_id:
                return item["event_id"]
        return None

    def get_assistant_messages(self, conversation_id, event_id, limit=8):
        rows = [item for item in self.messages if item["conversation_id"] == conversation_id and item["event_id"] == event_id]
        return rows[-limit:]

    def save_assistant_message(self, conversation_id, event_id, role, content, created_at=None):
        self.messages.append({
            "conversation_id": conversation_id, "event_id": event_id,
            "role": role, "content": content, "created_at": created_at or "",
        })

    def get_similar_incidents(self, **_kwargs):
        return []


class FakeOrchestrator:
    def __init__(self):
        self.db = FakeDatabase()

    def get_full_event(self, event_id):
        return example_event() if event_id == "incident-1" else None


class TestIncidentAssistant(unittest.TestCase):
    def test_unresolved_sop_id_does_not_create_a_source_reference(self):
        result = build_assistant_response(example_event(), "Show the relevant SOP section")
        self.assertEqual(result["incident_context"]["alarm_id"], "ALM-P02-HP")
        self.assertEqual(result["incident_context"]["equipment"], "Pump-02")
        self.assertEqual(result["incident_context"]["timestamp"], "2026-10-16T10:00:00Z")
        self.assertEqual(result["supporting_readings"][0]["value"], 56)
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["sop_resolution"]["status"], "document_not_found")
        self.assertEqual(result["uncertainty_status"], "insufficient_approved_procedure")
        self.assertTrue(result["read_only"])

    def test_missing_sop_returns_explicit_insufficient_guidance(self):
        event = example_event()
        event["sop_match"] = {"sop_id": "SOP-NONE", "retrieved_chunks": []}
        result = build_assistant_response(event, "What procedure should I follow?")
        self.assertEqual(result["uncertainty_status"], "insufficient_approved_procedure")
        self.assertIn("No applicable approved SOP passage was retrieved", result["answer"])
        self.assertEqual(result["sources"], [])

    def test_unverified_matching_sop_is_shown_as_reference_not_approved_guidance(self):
        event = example_event()
        event["sop_match"] = {
            "sop_id": "SOP-DEMO-1",
            "retrieved_chunks": [{
                "text": "Check the documented flow trend before drawing an incident conclusion.",
                "section": "Section 2.1",
                "step_number": None,
                "payload": {"sop_id": "SOP-DEMO-1", "section": "Section 2.1"},
            }],
        }
        result = build_assistant_response(
            event, "What does the retrieved procedure cover?",
            sop_document_loader=lambda _sop_id: {
                "sop_id": "SOP-DEMO-1", "title": "Demo procedure",
                "equipment_id": "Pump-02", "approved": False,
                "approval_status": "unverified",
                "steps": ["Check the documented flow trend before drawing an incident conclusion."],
            },
        )
        reference = result["operator_response"]["relevant_sop"]
        self.assertEqual(reference["label"], "REFERENCE ONLY — NOT APPROVED")
        self.assertFalse(reference["approved"])
        self.assertEqual(reference["passages"][0]["text"],
                         "Check the documented flow trend before drawing an incident conclusion.")
        self.assertIn("REFERENCE ONLY — NOT APPROVED", result["answer"])
        self.assertEqual(result["operator_response"]["resolution_criteria"],
                         "Not established by retrieved approved guidance.")

    def test_why_answer_marks_cause_as_hypothesis_and_keeps_score_semantics(self):
        result = build_assistant_response(example_event(), "Why did this alarm trigger?")
        self.assertIn("not proof of causation", result["answer"])
        self.assertEqual(result["incident_context"]["evidence_score_type"], "normalized contributor ranking heuristic; not a probability")
        self.assertEqual(result["supporting_events"][0]["timestamp"], "2026-10-16T09:59:00Z")

    def test_incident_analysis_remains_complete_when_no_sop_is_retrieved(self):
        event = example_event()
        event["sop_match"] = {
            "sop_id": "SOP-NONE", "retrieved_chunks": [], "retrieval_status": "no_match"
        }
        result = build_assistant_response(event, "Why did this alarm trigger?")
        self.assertEqual(result["uncertainty_status"], "hypothesis_requires_operator_verification")
        self.assertIn("Flow reduction followed by pressure rise", result["operator_response"]["interpretation"][0])
        self.assertEqual(result["supporting_readings"][0]["tag"], "FIT-02-FLW")
        self.assertEqual(result["sources"], [])
        self.assertTrue(any("No applicable approved SOP passage" in item
                            for item in result["operator_response"]["data_limitations"]))

    def test_unavailable_sop_retrieval_is_reported_without_replacing_incident_analysis(self):
        event = example_event()
        event["sop_match"] = {
            "sop_id": "SOP-NONE", "retrieved_chunks": [], "retrieval_status": "unavailable"
        }
        result = build_assistant_response(event, "Why did this alarm trigger?")
        self.assertIn("is recorded active on Pump-02", result["operator_response"]["bottom_line"])
        self.assertEqual(result["sop_resolution"]["status"], "retrieval_unavailable")
        self.assertEqual(result["sources"], [])
        self.assertTrue(any("SOP retrieval was unavailable" in item
                            for item in result["operator_response"]["data_limitations"]))

    def test_context_deviation_is_attached_only_to_the_observed_timestamp(self):
        context = {"window": {"start": "2026-10-16T09:30:00Z", "end": "2026-10-16T10:00:00Z"},
                   "readings": [
                       {"tag": "FIT-02-FLW", "value": 80, "timestamp": "2026-10-16T09:58:00Z", "timestamp_utc": "2026-10-16T09:58:00Z"},
                       {"tag": "FIT-02-FLW", "value": 56, "timestamp": "2026-10-16T09:59:00Z", "timestamp_utc": "2026-10-16T09:59:00Z"},
                   ],
                   "related_events": []}
        result = build_assistant_response(example_event(), "Why did this alarm trigger?", context=context)
        self.assertNotIn("deviation_pct", result["supporting_readings"][0])
        self.assertEqual(result["supporting_readings"][1]["deviation_pct"], -31.7)

    def test_historical_readings_change_explanation_without_copying_alarm_deviation(self):
        historical = [
            {"tag": "FIT-02-FLW", "value": 100, "unit": "L/min", "equipment_id": "Pump-02",
             "timestamp": "2026-10-16T09:57:00Z", "timestamp_utc": "2026-10-16T09:57:00Z"},
            {"tag": "FIT-02-FLW", "value": 75, "unit": "L/min", "equipment_id": "Pump-02",
             "timestamp": "2026-10-16T09:59:00Z", "timestamp_utc": "2026-10-16T09:59:00Z"},
        ]
        context = {"window": {"start": "2026-10-16T09:30:00Z", "end": "2026-10-16T10:00:00Z"},
                   "readings": historical,
                   "trend_summaries": summarize_readings(historical, "2026-10-16T10:00:00Z"),
                   "related_events": [], "operator_actions": []}
        result = build_assistant_response(example_event(), "What changed before the alarm?", context=context)
        self.assertIn("from 100 L/min", result["answer"])
        self.assertIn("to 75 L/min", result["answer"])
        self.assertIn("-25.0%", result["answer"])
        self.assertNotIn("-31.7%", result["answer"])
        self.assertIn("Bottom line", result["answer"])
        self.assertIn("Evidence", result["answer"])
        self.assertNotIn("2026-10-16T09:59:00Z", result["answer"])
        trend = next(item for item in result["operator_response"]["evidence"] if item["kind"] == "trend")
        self.assertEqual(trend["first_timestamp"], "2026-10-16T09:57:00Z")
        self.assertEqual(trend["last_timestamp"], "2026-10-16T09:59:00Z")
        self.assertEqual(trend["absolute_change_unit"], "L/min")
        self.assertNotIn("deviation_pct", result["supporting_readings"][0])

    def test_operator_response_uses_percentage_points_and_separates_relative_change(self):
        readings = [
            {"tag": "VLV-04-POS", "value": 80, "unit": "%", "timestamp": "2026-10-16T09:57:00Z"},
            {"tag": "VLV-04-POS", "value": 47.48, "unit": "%", "timestamp": "2026-10-16T09:59:00Z"},
        ]
        context = {"window": {"start": "2026-10-16T09:30:00Z", "end": "2026-10-16T10:00:00Z"},
                   "readings": readings, "trend_summaries": summarize_readings(readings, "2026-10-16T10:00:00Z"),
                   "related_events": [], "operator_actions": []}
        result = build_assistant_response(example_event(), "What changed before the alarm?", context=context)
        trend = next(item for item in result["operator_response"]["evidence"] if item["kind"] == "trend")
        self.assertEqual(trend["absolute_change_unit"], "percentage points")
        self.assertAlmostEqual(trend["absolute_change"], -32.52)
        self.assertAlmostEqual(trend["relative_percentage_change"], -40.65, places=2)
        self.assertIn("percentage points", trend["summary"])
        self.assertIn("relative", trend["summary"])

    def test_timestamp_discrepancy_is_operator_facing_without_raw_iso(self):
        context = {
            "window": {"start": "2026-10-16T09:30:00Z", "end": "2026-10-16T10:00:00Z"},
            "readings": [], "related_events": [], "operator_actions": [],
            "selected_event": {"timestamp_discrepancy": True,
                               "timestamp": "2026-10-16T10:00:00Z",
                               "event_story_alarm_timestamp": "2026-10-16T10:00:03Z",
                               "timestamp_source": "candidate_events.trigger_timestamp"},
            "missing_data": ["candidate_events.trigger_timestamp differs from event-story alarm timestamp"],
        }
        result = build_assistant_response(example_event(), "Why did this alarm trigger?", context=context)
        self.assertIn("differ", " ".join(result["operator_response"]["data_limitations"]).lower())
        self.assertNotIn("candidate_events.trigger_timestamp", result["answer"])
        self.assertNotIn("2026-10-16T10:00:00Z", result["answer"])

    def test_operator_response_explicitly_limits_unverified_sop_and_is_read_only(self):
        event = example_event()
        event["sop_match"] = {"sop_id": "SOP-NONE", "retrieved_chunks": []}
        result = build_assistant_response(event, "What procedure should I follow?")
        self.assertTrue(result["operator_response"]["read_only"])
        self.assertTrue(any("No applicable approved SOP passage was retrieved" in item for item in result["operator_response"]["data_limitations"]))
        self.assertIn("Data limitations", result["answer"])

    def test_operator_actions_and_empty_history_are_explicit(self):
        context = {"window": {"start": "2026-10-16T09:30:00Z", "end": "2026-10-16T10:00:00Z"},
                   "readings": [], "related_events": [], "operator_actions": []}
        result = build_assistant_response(example_event(), "Were any operator actions recorded?", context=context)
        self.assertIn("No relevant operator audit actions were recorded", result["answer"])
        empty = build_assistant_response(example_event(), "What changed in the last 30 minutes?", context=context)
        self.assertIn("No usable numeric historical readings", empty["answer"])

    def test_hypothetical_question_explains_weakening_hypothesis_and_checks(self):
        result = build_assistant_response(
            example_event(),
            "If the valve position returned to normal but discharge pressure remained high, what would that tell us, and what evidence would we need before identifying the cause?"
        )
        self.assertEqual(result["uncertainty_status"], "hypothetical_reasoning")
        self.assertIn("Hypothetical analysis", result["answer"])
        self.assertIn("weaken", result["answer"].lower())
        self.assertIn("not actually been observed", result["answer"].lower())
        self.assertGreaterEqual(len(result["immediate_checks"]), 2)
        self.assertTrue(any("freshness" in c.lower() or "runtime" in c.lower() for c in result["immediate_checks"]))

    def test_approved_sop_returns_steps_in_bottom_line_and_checks(self):
        import json
        from pathlib import Path
        document_path = Path(__file__).parents[1] / "sop_documents" / "valve_restriction.json"
        stored_steps = json.loads(document_path.read_text(encoding="utf-8"))["steps"]
        event = example_event()
        event["sop_match"] = {
            "sop_id": "SOP-P02-VLV-01",
            "sop_title": "Pump-02 Throttling Valve Restriction Remediation",
            "approved": True,
            "steps": stored_steps[:2],
        }
        # The repository's bundled demo procedure is intentionally unapproved.
        # This injected source models a document-control record with explicit,
        # traceable approval; its step text still comes from the stored file.
        approved_document = json.loads(document_path.read_text(encoding="utf-8"))
        approved_document.update({
            "approved": True,
            "approval_status": "approved",
            "approval_reference": "DOC-CONTROL-TEST-001",
        })
        result = build_assistant_response(
            event,
            "What are the steps to resolve this?",
            sop_document_loader=lambda sop_id: approved_document if sop_id == "SOP-P02-VLV-01" else None,
        )
        self.assertEqual(result["uncertainty_status"], "source_retrieved")
        self.assertIn("Approved procedure SOP-P02-VLV-01", result["operator_response"]["bottom_line"])
        self.assertEqual(len(result["operator_response"]["recommended_checks"]), 2)
        self.assertTrue(all(source["verified"] and source["approved"] for source in result["sources"]))
        self.assertIn("Approved procedure SOP-P02-VLV-01", result["question_answer"])

    def test_resolution_question_gets_safe_question_specific_fallback_without_inventing_sop(self):
        event = example_event()
        event["sop_match"] = {"sop_id": "SOP-NONE", "retrieved_chunks": [], "retrieval_status": "no_match"}
        result = build_assistant_response(event, "What steps does the operator need to follow to resolve the problem?")
        answer = result["question_answer"]
        self.assertIn("1. Confirm the alarm's current state on the HMI", answer)
        self.assertIn("7. Record the outcome", answer)
        self.assertIn("not an approved procedure", answer)
        self.assertFalse(result["solution"]["sop_status"]["approved"])

    def test_natural_action_wording_is_recognized_as_a_resolution_question(self):
        event = example_event()
        event["sop_match"] = {"sop_id": "SOP-NONE", "retrieved_chunks": [], "retrieval_status": "no_match"}
        result = build_assistant_response(event, "What actions to be taken to resolve this problem?")
        self.assertIn("general read-only verification steps", result["question_answer"])
        self.assertIn("Consult the applicable plant-approved SOP", result["question_answer"])
        self.assertNotIn("A physical cause has not been confirmed", result["question_answer"])

    def test_api_reports_unknown_incident_and_validation_errors(self):
        client = TestClient(create_app(orchestrator=FakeOrchestrator()))
        self.assertEqual(client.post("/api/assistant/ask", json={"event_id": "missing", "question": "Why?"}).status_code, 404)
        self.assertEqual(client.post("/api/assistant/ask", json={"event_id": "incident-1", "question": "?"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
