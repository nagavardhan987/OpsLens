"""
OpsLens - AI Answer Quality & Incident Context Relevance Test Suite

Verifies:
Test A: InletWorks-01 on-topic question uses InletWorks-01 evidence (DPT-110-SCR, FIT-110-IN).
Test B: InletWorks-01 sensor interpretation question succeeds with valid engineering units (kPa, m³/h) and deltas.
Test C: Unicode punctuation (non-breaking hyphens like DPT‑110‑SCR, narrow no-break space) passes grounding validation.
Test D: Question referencing valve restriction while InletWorks-01 is selected triggers incident relevance check,
        corrects false flow reduction premise with actual data, and asks operator to switch or clarify.
Test E: Pump-02 question referencing valve restriction on Pump-02 is on-topic and uses Pump-02 evidence.
Test F: Provider failure simulation falls back gracefully to a direct question-specific evidence-based answer.
Test G: Successful LLM response sets llm_used=True and fallback_used=False.
"""

import json
import unittest

from assistant import (
    answer_incident_question,
    build_assistant_response,
    compact_llm_context,
    _llm_answer_rejection_reason,
    detect_incident_mismatch,
    format_mismatch_response,
)


def make_inletworks_incident():
    return {
        "event_id": "inletworks-incident-01",
        "trigger_timestamp": "2026-11-01T13:12:08Z",
        "candidate": {
            "primary_tag": "DPT-110-SCR",
            "alarm_id": "ALM-SCR-110-DP",
            "primary_alarm": True,
            "alarm_severity": "HIGH",
            "trigger_timestamp": "2026-11-01T13:12:08Z",
        },
        "correlated": {"equipment_id": "InletWorks-01"},
        "story": {
            "causal_label": "Screen differential pressure high",
            "steps": [
                {
                    "tag": "DPT-110-SCR",
                    "timestamp": "2026-11-01T13:12:04Z",
                    "description": "Screen differential pressure (DPT-110-SCR) increased by 380.0%",
                    "value_before": 0.99,
                    "value_after": 4.8,
                },
                {
                    "tag": "ALM-SCR-110-DP",
                    "timestamp": "2026-11-01T13:12:08Z",
                    "description": "Coarse screen differential pressure high annunciated",
                    "value_before": 0,
                    "value_after": 1,
                },
            ],
        },
        "evidence": {"likely_contributor_tag": "DPT-110-SCR", "confidence_score": 0.88},
        "sop_match": {},
        "runtime_alarm_state": {"tag": "ALM-SCR-110-DP", "active": True, "observed": True, "timestamp": "2026-11-01T13:12:08Z"},
    }


def make_inletworks_context():
    return {
        "selected_event": {"timestamp": "2026-11-01T13:12:08Z", "equipment_id": "InletWorks-01", "alarm_id": "ALM-SCR-110-DP"},
        "missing_data": [],
        "window": {"start": "2026-11-01T12:42:08Z", "end": "2026-11-01T13:12:08Z", "duration_minutes": 30},
        "trend_summaries": [
            {
                "tag": "DPT-110-SCR",
                "unit": "kPa",
                "reading_count": 2,
                "first_observed": {"value": 0.99, "timestamp": "2026-11-01T13:10:56Z"},
                "last_observed": {"value": 4.8, "timestamp": "2026-11-01T13:12:04Z"},
                "absolute_change": 3.81,
                "percentage_change": 384.8,
            },
            {
                "tag": "FIT-110-IN",
                "unit": "m³/h",
                "reading_count": 2,
                "first_observed": {"value": 2012.82, "timestamp": "2026-11-01T13:10:56Z"},
                "last_observed": {"value": 2103.11, "timestamp": "2026-11-01T13:12:04Z"},
                "absolute_change": 90.29,
                "percentage_change": 4.5,
            },
        ],
    }


def make_pump_incident():
    return {
        "event_id": "pump-incident-02",
        "trigger_timestamp": "2026-10-16T10:00:00Z",
        "candidate": {
            "primary_tag": "PIT-02-PRS",
            "alarm_id": "ALM-P02-HP",
            "primary_alarm": True,
            "alarm_severity": "HIGH",
            "trigger_timestamp": "2026-10-16T10:00:00Z",
        },
        "correlated": {"equipment_id": "Pump-02"},
        "story": {
            "causal_label": "Flow reduction followed by pressure rise",
            "steps": [
                {"tag": "VLV-04-POS", "timestamp": "2026-10-16T09:58:30Z", "description": "Valve restricted", "value_before": 80, "value_after": 22},
                {"tag": "FIT-02-FLW", "timestamp": "2026-10-16T09:59:00Z", "description": "Flow decreased", "value_before": 82, "value_after": 56},
                {"tag": "PIT-02-PRS", "timestamp": "2026-10-16T09:59:45Z", "description": "Discharge pressure rose", "value_before": 4.8, "value_after": 6.8},
                {"tag": "ALM-P02-HP", "timestamp": "2026-10-16T10:00:00Z", "description": "High pressure alarm", "value_before": 0, "value_after": 1},
            ],
        },
        "evidence": {"likely_contributor_tag": "VLV-04-POS", "confidence_score": 0.85},
        "sop_match": {},
        "runtime_alarm_state": {"tag": "ALM-P02-HP", "active": True, "observed": True, "timestamp": "2026-10-16T10:00:01Z"},
    }


def make_pump_context():
    return {
        "selected_event": {"timestamp": "2026-10-16T10:00:00Z", "equipment_id": "Pump-02", "alarm_id": "ALM-P02-HP"},
        "missing_data": [],
        "window": {"start": "2026-10-16T09:30:00Z", "end": "2026-10-16T10:00:00Z", "duration_minutes": 30},
        "trend_summaries": [
            {
                "tag": "VLV-04-POS", "unit": "%", "reading_count": 2,
                "first_observed": {"value": 80.0, "timestamp": "2026-10-16T09:30:00Z"},
                "last_observed": {"value": 22.0, "timestamp": "2026-10-16T09:58:30Z"},
                "absolute_change": -58.0, "percentage_change": -72.5,
            },
            {
                "tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
                "first_observed": {"value": 82.0, "timestamp": "2026-10-16T09:30:00Z"},
                "last_observed": {"value": 56.0, "timestamp": "2026-10-16T09:59:00Z"},
                "absolute_change": -26.0, "percentage_change": -31.7,
            },
            {
                "tag": "PIT-02-PRS", "unit": "bar", "reading_count": 2,
                "first_observed": {"value": 4.8, "timestamp": "2026-10-16T09:30:00Z"},
                "last_observed": {"value": 6.8, "timestamp": "2026-10-16T09:59:45Z"},
                "absolute_change": 2.0, "percentage_change": 41.7,
            },
        ],
    }


class TestAiAnswerQuality(unittest.TestCase):
    """Verifies all 7 criteria (A through G) from the OpsLens AI upgrade request."""

    def test_case_a_inletworks_on_topic_uses_inletworks_evidence(self):
        """Test A: InletWorks-01 question uses InletWorks-01 evidence only."""
        event = make_inletworks_incident()
        context = make_inletworks_context()
        question = "Why did this alarm trigger?"

        result = build_assistant_response(event, question, context=context)
        self.assertEqual(result["incident_context"]["equipment"], "InletWorks-01")
        self.assertIn("DPT-110-SCR", result["question_answer"])
        self.assertNotIn("VLV-04", result["question_answer"])
        self.assertNotIn("Pump-02", result["question_answer"])

    def test_case_b_sensor_interpretation_passes_grounding_with_engineering_units(self):
        """Test B: LLM answer referencing kPa and m³/h passes grounding validation."""
        event = make_inletworks_incident()
        context = make_inletworks_context()
        llm_answer = (
            "DPT-110-SCR rose from 0.99 to 4.8 kPa before ALM-SCR-110-DP, consistent with screen loading. "
            "Inlet flow FIT-110-IN increased from 2012.82 to 2103.11 m³/h (+4.5% relative change), "
            "indicating higher inlet throughput; this association does not confirm physical blockage. "
            "Verify the differential pressure transmitter and check rake status on the HMI."
        )

        result = answer_incident_question(
            event,
            "Explain the differential pressure and inlet flow trends.",
            context=context,
            llm_complete=lambda _p: json.dumps({"answer": llm_answer}),
        )

        self.assertTrue(result["llm_used"])
        self.assertFalse(result["fallback_used"])
        self.assertIn("DPT-110-SCR", result["question_answer"])
        self.assertIn("2103.11 m³/h", result["question_answer"])

    def test_case_c_unicode_punctuation_normalizes_and_passes_grounding(self):
        """Test C: Unicode non-breaking hyphens and narrow spaces pass grounding validation."""
        event = make_inletworks_incident()
        context = make_inletworks_context()
        grounded = build_assistant_response(event, "What caused this?", context=context)
        compact = compact_llm_context(event, context, grounded)

        unicode_answer = (
            "The DPT\u2011110\u2011SCR sensor rose to 4.8\u202fkPa, a 380\u202f% increase before the alarm, "
            "indicating the differential pressure likely triggered the alarm. The operator should first verify the DPT\u2011110\u2011SCR reading."
        )

        reason = _llm_answer_rejection_reason(unicode_answer, grounded, compact, False)
        self.assertIsNone(reason, f"Unexpected rejection: {reason}")

    def test_case_d_mismatch_detected_and_politely_corrected(self):
        """Test D: Asking about valve restriction & flow reduction on InletWorks-01 triggers mismatch detection."""
        event = make_inletworks_incident()
        context = make_inletworks_context()
        mismatched_question = (
            "What evidence suggests the valve restriction caused the flow reduction and pressure increase, "
            "and what should the operator verify first?"
        )

        mismatch = detect_incident_mismatch("InletWorks-01", "ALM-SCR-110-DP", context["trend_summaries"], mismatched_question)
        self.assertIsNotNone(mismatch)
        self.assertTrue(mismatch["mismatch"])
        self.assertEqual(mismatch["foreign_equipment"], "Pump-02")
        self.assertIn("valve", mismatch["foreign_terms"])
        self.assertTrue(len(mismatch["contradictions"]) > 0)

        # Full assistant response on mismatch
        result = answer_incident_question(
            event, mismatched_question, context=context,
            llm_complete=lambda _p: json.dumps({
                "answer": (
                    "The selected incident is for InletWorks-01 (ALM-SCR-110-DP), which contains screen differential-pressure "
                    "and inlet-flow records, not Pump-02 valve-position evidence. Furthermore, recorded telemetry shows FIT-110-IN "
                    "inlet flow increased from 2012.82 to 2103.11 m³/h (+4.5%), rather than reducing. "
                    "Would you like to switch to the Pump-02 incident or clarify your question about InletWorks-01?"
                )
            })
        )

        answer_text = result["question_answer"]
        self.assertIn("InletWorks-01", answer_text)
        self.assertIn("Pump-02", answer_text)
        self.assertIn("FIT-110-IN", answer_text)
        self.assertIn("rather than reducing", answer_text)
        self.assertIn("switch", answer_text.lower())

    def test_case_e_pump02_valve_question_is_on_topic_and_uses_pump02_data(self):
        """Test E: Pump-02 valve question on Pump-02 is on-topic and uses Pump-02 evidence."""
        event = make_pump_incident()
        context = make_pump_context()
        question = "What evidence suggests the valve restriction caused the flow reduction?"

        mismatch = detect_incident_mismatch("Pump-02", "ALM-P02-HP", context["trend_summaries"], question)
        self.assertIsNone(mismatch, "Should NOT detect mismatch when question matches equipment")

        result = build_assistant_response(event, question, context=context)
        self.assertEqual(result["incident_context"]["equipment"], "Pump-02")
        self.assertIn("VLV-04-POS", result["question_answer"])
        self.assertNotIn("InletWorks-01", result["question_answer"])
        self.assertNotIn("DPT-110-SCR", result["question_answer"])

    def test_case_f_llm_failure_falls_back_to_question_specific_answer(self):
        """Test F: Provider failure simulation falls back gracefully to direct answer without report template."""
        event = make_inletworks_incident()
        context = make_inletworks_context()

        def timeout_llm(_prompt):
            raise TimeoutError("Simulated LLM network timeout")

        result = answer_incident_question(
            event, "Why did this alarm trigger?", context=context, llm_complete=timeout_llm
        )

        self.assertTrue(result["fallback_used"])
        self.assertFalse(result["llm_used"])
        self.assertEqual(result["fallback_reason"], "llm_unavailable")
        self.assertIn("DPT-110-SCR", result["question_answer"])
        self.assertNotIn("Bottom line", result["question_answer"])
        self.assertNotIn("\nEvidence\n", result["question_answer"])

    def test_case_g_successful_llm_sets_correct_status_flags(self):
        """Test G: Successful LLM answer sets llm_used=True and fallback_used=False."""
        event = make_pump_incident()
        context = make_pump_context()
        llm_response = (
            "VLV-04-POS closed by 58 percentage points from 80% to 22%, followed by FIT-02-FLW dropping from 82 to 56 L/min "
            "and discharge pressure PIT-02-PRS rising to 6.8 bar, triggering ALM-P02-HP. This temporal sequence supports "
            "the valve restriction hypothesis but requires physical verification on the HMI faceplate."
        )

        result = answer_incident_question(
            event, "Explain what caused the alarm.", context=context,
            llm_complete=lambda _p: json.dumps({"answer": llm_response})
        )

        self.assertTrue(result["llm_used"])
        self.assertFalse(result["fallback_used"])
        self.assertIsNone(result["fallback_reason"])
        self.assertEqual(result["question_answer"], llm_response)


if __name__ == "__main__":
    unittest.main()
