import unittest
import json

from assistant import _llm_answer_rejection_reason, answer_incident_question


def incident():
    return {
        "event_id": "question-specific-incident",
        "trigger_timestamp": "2026-10-16T10:00:00Z",
        "candidate": {
            "primary_tag": "PIT-02-PRS",
            "alarm_id": "ALM-P02-HP",
            "primary_alarm": True,
            "alarm_severity": "HIGH",
            "trigger_timestamp": "2026-10-16T10:00:00Z",
        },
        "story": {
            "causal_label": "Flow reduction followed by pressure rise",
            "steps": [
                {"tag": "FIT-02-FLW", "timestamp": "2026-10-16T09:59:00Z", "description": "Flow decreased", "value_before": 82, "value_after": 56},
                {"tag": "ALM-P02-HP", "timestamp": "2026-10-16T10:00:00Z", "description": "High pressure alarm", "value_before": 0, "value_after": 1},
            ],
        },
        "evidence": {"likely_contributor_tag": "FIT-02-FLW", "confidence_score": 0.69},
        "sop_match": {},
        "runtime_alarm_state": {"tag": "ALM-P02-HP", "active": True, "observed": True, "timestamp": "2026-10-16T10:00:01Z"},
    }


class AssistantQuestionAnswerTests(unittest.TestCase):
    question = (
        "Based on the recorded sensor trends, explain how the increase in screen differential pressure may have contributed "
        "to the coarse screen alarm. What does the change in inlet flow indicate, and what additional information would help verify the suspected cause?"
    )

    @staticmethod
    def provider_failure(_prompt):
        raise TimeoutError("test provider timeout")

    def test_fallback_question_answer_is_direct_and_not_the_formatted_incident_report(self):
        result = answer_incident_question(
            incident(), "What caused this alarm?", llm_complete=self.provider_failure,
        )

        self.assertTrue(result["fallback_used"])
        self.assertIn("Flow reduction followed by pressure rise", result["question_answer"])
        self.assertIn("FIT-02-FLW", result["question_answer"])
        self.assertNotIn("Bottom line", result["question_answer"])
        self.assertNotIn("\nEvidence\n", result["question_answer"])

    def test_procedure_question_gets_question_specific_safe_steps_without_fabricating_sop(self):
        result = answer_incident_question(
            incident(), "What steps should the operator follow to resolve the problem?",
            llm_complete=self.provider_failure,
        )

        answer = result["question_answer"]
        self.assertIn("general read-only verification steps", answer)
        self.assertIn("Confirm the alarm's current state on the HMI", answer)
        self.assertIn("No applicable approved SOP content was retrieved", answer)
        self.assertNotIn("Approved procedure", answer)
        self.assertNotIn("Bottom line", answer)

    def test_valid_sensor_interpretation_passes_grounding_with_alarm_tag_nearby(self):
        event = incident()
        event["event_id"] = "screen-alarm-incident"
        event["candidate"].update({"primary_tag": "DPT-110-SCR", "alarm_id": "ALM-SCR-110-DP"})
        event["story"] = {"causal_label": "Screen differential pressure alarm", "steps": [
            {"tag": "DPT-110-SCR", "timestamp": "2026-11-01T13:12:04Z", "description": "Screen differential pressure rose", "value_before": 0.99, "value_after": 4.8},
            {"tag": "ALM-SCR-110-DP", "timestamp": "2026-11-01T13:12:08Z", "description": "Coarse screen differential pressure alarm", "value_before": 0, "value_after": 1},
        ]}
        context = {"selected_event": {"timestamp": "2026-11-01T13:12:08Z"}, "missing_data": [], "window": {
            "start": "2026-11-01T12:42:08Z", "end": "2026-11-01T13:12:08Z", "duration_minutes": 30,
        }, "trend_summaries": [
            {"tag": "DPT-110-SCR", "unit": "kPa", "reading_count": 2, "first_observed": {"value": 0.99, "timestamp": "2026-11-01T13:10:56Z"}, "last_observed": {"value": 4.8, "timestamp": "2026-11-01T13:12:04Z"}, "absolute_change": 3.81, "percentage_change": 384.8},
            {"tag": "FIT-110-IN", "unit": "m³/h", "reading_count": 2, "first_observed": {"value": 2012.82, "timestamp": "2026-11-01T13:10:56Z"}, "last_observed": {"value": 2103.11, "timestamp": "2026-11-01T13:12:04Z"}, "absolute_change": 90.29, "percentage_change": 4.5},
        ]}
        llm_answer = (
            "DPT-110-SCR rose from 0.99 to 4.8 kPa before ALM-SCR-110-DP. This rise is consistent with increased resistance or screen loading, "
            "so it may have contributed to the alarm, but it does not confirm a physical blockage. FIT-110-IN increased from 2012.82 to 2103.11 m³/h, "
            "indicating higher recorded inlet throughput that could increase screen loading; timing does not prove causation. Screen/rake cleaning status, "
            "differential-pressure instrument condition, and synchronized upstream/downstream flow readings would help test the suspected relationship."
        )
        result = answer_incident_question(
            event, self.question, context=context,
            llm_complete=lambda _prompt: json.dumps({"answer": llm_answer}),
        )

        self.assertTrue(result["llm_used"], result.get("fallback_reason"))
        self.assertFalse(result["fallback_used"])
        self.assertIn("increased resistance", result["question_answer"])
        self.assertIn("higher recorded inlet throughput", result["question_answer"])
        self.assertIn("instrument condition", result["question_answer"])

    def test_draft_sop_action_language_only_rejects_procedure_answers(self):
        grounded = {"answer": "", "sources": [], "sop_resolution": {"status": "reference_unapproved"}}
        compact = {"numeric_facts": [], "trend_summaries": [], "sop_passages": []}
        explanation = "Check the transmitter reading and compare it with the flow trend to assess the suspected cause."

        self.assertIsNone(_llm_answer_rejection_reason(explanation, grounded, compact, wants_procedure=False))
        self.assertEqual(
            _llm_answer_rejection_reason(explanation, grounded, compact, wants_procedure=True),
            "unverified_sop_actionable_language",
        )

    def test_interpretation_fallback_is_concise_and_uses_only_selected_trends(self):
        event = incident()
        event["event_id"] = "screen-alarm-incident"
        event["candidate"].update({"primary_tag": "DPT-110-SCR", "alarm_id": "ALM-SCR-110-DP"})
        context = {"selected_event": {"timestamp": "2026-11-01T13:12:08Z"}, "missing_data": [], "trend_summaries": [
            {"tag": "DPT-110-SCR", "unit": "kPa", "reading_count": 2, "first_observed": {"value": 0.99, "timestamp": "2026-11-01T13:10:56Z"}, "last_observed": {"value": 4.8, "timestamp": "2026-11-01T13:12:04Z"}, "absolute_change": 3.81, "percentage_change": 384.8},
            {"tag": "FIT-110-IN", "unit": "m³/h", "reading_count": 2, "first_observed": {"value": 2012.82, "timestamp": "2026-11-01T13:10:56Z"}, "last_observed": {"value": 2103.11, "timestamp": "2026-11-01T13:12:04Z"}, "absolute_change": 90.29, "percentage_change": 4.5},
        ]}
        result = answer_incident_question(event, self.question, context=context, llm_complete=self.provider_failure)

        self.assertTrue(result["fallback_used"])
        self.assertIn("increasing resistance or screen loading", result["question_answer"])
        self.assertIn("higher recorded inlet throughput", result["question_answer"])
        self.assertIn("screen/rake cleaning status", result["question_answer"])
        self.assertNotIn("Bottom line", result["question_answer"])
        self.assertNotIn("Evidence\n", result["question_answer"])


if __name__ == "__main__":
    unittest.main()
