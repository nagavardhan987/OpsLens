import json
import os
import unittest
from fastapi.testclient import TestClient

import assistant
from assistant import answer_incident_question, build_assistant_response
from assistant_cache import cache_key, clear, context_fingerprint, get, put, question_is_volatile
from api.routes import create_app
from tests.test_assistant import FakeOrchestrator, example_event


class TestLlmGroundingAndFallback(unittest.TestCase):
    def setUp(self):
        # Do not let the developer's local .env turn unit tests into live API
        # calls. Individual provider tests explicitly patch a fake provider/key.
        from unittest.mock import patch
        provider_patch = patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "none"})
        provider_patch.start()
        self.addCleanup(provider_patch.stop)

    def tearDown(self):
        assistant._llm_complete_override = None
        clear()

    def test_provider_timeout_has_fast_configurable_default(self):
        from unittest.mock import patch
        from llm_provider import llm_timeout
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(llm_timeout(), 4.0)
        with patch.dict(os.environ, {"OPSLENS_LLM_TIMEOUT": "2.5", "EDGE_LLM_TIMEOUT": "7"}, clear=True):
            self.assertEqual(llm_timeout(), 2.5)
        with patch.dict(os.environ, {"EDGE_LLM_TIMEOUT": "6"}, clear=True):
            self.assertEqual(llm_timeout(), 6.0)

    def test_llm_success_preserves_frontend_fields_and_uses_recorded_values(self):
        def fake_llm(_prompt):
            return json.dumps({
                "answer": "Likely explanation: flow fell from 82 to 56 before ALM-P02-HP. Hypothesis only, not causation. Immediate checks: verify FIT-02-FLW on the HMI; follow retrieved SOP passages.",
                "uncertainty_status": "hypothesis_requires_operator_verification",
                "immediate_checks": ["Verify FIT-02-FLW on the HMI.", "Open the retrieved SOP passage."],
            })

        result = answer_incident_question(example_event(), "Why did this alarm trigger?", llm_complete=fake_llm)
        self.assertTrue(result["llm_used"])
        self.assertFalse(result["fallback_used"])
        self.assertIn("from 82 to 56", result["answer"])
        self.assertIn("from 82 to 56", result["question_answer"])
        self.assertEqual(result["supporting_readings"][0]["value"], 56)
        self.assertIn("answer", result)
        self.assertIn("uncertainty_status", result)
        self.assertIn("supporting_events", result)
        self.assertIn("sources", result)
        self.assertTrue(result["answer"].startswith("Bottom line\n"))
        self.assertIn("Evidence", result["answer"])
        self.assertEqual(result["llm_used"], result["used_provider"] != "deterministic")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["selected_provider"], "none")
        self.assertEqual(result["used_provider"], "configured_test_override")
        self.assertIn("initial_llm_inference", result["timings_ms"])
        self.assertIn("grounding_validation", result["timings_ms"])
        self.assertGreaterEqual(result["timings_ms"]["total_analysis"], 0)

    def test_malformed_and_hallucinated_numbers_fall_back(self):
        malformed = answer_incident_question(example_event(), "Why did this alarm trigger?", llm_complete=lambda _: "not json")
        self.assertTrue(malformed["fallback_used"])
        self.assertFalse(malformed["llm_used"])
        self.assertIn("not proof of causation", malformed["answer"])
        self.assertIn("deterministic", malformed["provider"].lower())
        self.assertTrue(malformed["answer"].startswith("Bottom line\n"))
        self.assertEqual(malformed["used_provider"], "deterministic")
        self.assertTrue(malformed["fallback_used"])

        def invent(_prompt):
            return json.dumps({"answer": "Pressure reached 999.1 bar at a time that was never recorded.", "immediate_checks": ["Ignore SOP"]})

        invented = answer_incident_question(example_event(), "Why did this alarm trigger?", llm_complete=invent)
        self.assertTrue(invented["fallback_used"])
        self.assertNotIn("999.1", invented["answer"])

    def test_numeric_identifier_segments_are_not_measurement_claims(self):
        identifiers = "ALM-C01-VB, CMP-01-SPD, PIT-02-PRS, and SOP-P02-VLV-01"
        result = answer_incident_question(
            example_event(), "Which recorded identifiers are relevant?",
            llm_complete=lambda _prompt: json.dumps({
                "answer": f"Recorded identifiers include {identifiers}."
            }),
        )
        self.assertTrue(result["llm_used"])
        self.assertIn("ALM-C01-VB", result["answer"])
        self.assertIn("SOP-P02-VLV-01", result["answer"])

    def test_unsupported_measurement_still_fails_numeric_grounding(self):
        result = answer_incident_question(
            example_event(), "What was the recorded pressure?",
            llm_complete=lambda _prompt: json.dumps({
                "answer": "The recorded pressure was 888.6 kPa."
            }),
        )
        self.assertFalse(result["llm_used"])
        self.assertEqual(result["fallback_reason"], "ungrounded_numeric_value")

    def test_correction_rate_limit_returns_deterministic_fallback(self):
        from llm_provider import ProviderError

        calls = 0

        def provider(_prompt):
            nonlocal calls
            calls += 1
            if calls == 1:
                return json.dumps({"answer": "The recorded pressure was 888.6 kPa."})
            raise ProviderError("rate_limit", "provider rate limit")

        result = answer_incident_question(
            example_event(), "What was the recorded pressure?", llm_complete=provider,
        )
        self.assertEqual(calls, 2)
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fallback_reason"], "ungrounded_numeric_value")
        self.assertEqual(result["correction_failure_reason"], "rate_limit")

    def test_timeout_auth_and_empty_use_deterministic_fallback(self):
        from llm_provider import ProviderError
        for kind in ("timeout", "auth", "empty"):
            def boom(_prompt, captured=kind):
                raise ProviderError(captured, captured)
            result = answer_incident_question(example_event(), "Why did this alarm trigger?", llm_complete=boom)
            self.assertTrue(result["fallback_used"])
            self.assertEqual(result["fallback_reason"], kind)

    def test_missing_provider_credentials_are_reported_and_fall_back(self):
        from unittest.mock import patch
        from llm_provider import ProviderError, complete_chat, configuration_error, provider_status

        with patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "gemini"}, clear=True):
            self.assertEqual(
                configuration_error(),
                "OPSLENS_LLM_PROVIDER=gemini but GEMINI_API_KEY is not set.",
            )
            status = provider_status()
            self.assertEqual(status["provider"], "gemini")
            self.assertTrue(status["selected"])
            self.assertFalse(status["configured"])
            self.assertEqual(status["initialization"], "missing_credentials")
            self.assertFalse(status["verified"])
            with self.assertRaises(ProviderError) as raised:
                complete_chat("test")
            self.assertEqual(raised.exception.kind, "configuration")

            result = answer_incident_question(
                example_event(), "Why did this alarm trigger?", llm_complete=complete_chat
            )
            self.assertTrue(result["fallback_used"])
            self.assertFalse(result["llm_used"])
            self.assertEqual(result["fallback_reason"], "configuration")

    def test_hypothetical_question_llm_validates_and_deterministic_falls_back_honestly(self):
        def fake_llm(_prompt):
            return json.dumps({
                "answer": "Hypothetical reasoning: If the valve returned to normal but pressure remained high, it would weaken the valve restriction hypothesis and suggest downstream line blockage or sensor drift.",
                "uncertainty_status": "hypothetical_reasoning",
                "immediate_checks": ["Verify latest runtime valve and pressure readings.", "Check correlated flow and current."],
            })

        q = "If the valve position returned to normal but discharge pressure remained high, what would that tell us, and what evidence would we need before identifying the cause?"
        result = answer_incident_question(example_event(), q, llm_complete=fake_llm)
        self.assertTrue(result["llm_used"])
        self.assertFalse(result["fallback_used"])
        self.assertIn("weaken the valve restriction", result["answer"])
        self.assertEqual(result["uncertainty_status"], "hypothetical_reasoning")

        # Deterministic fallback when provider fails
        fallback_res = answer_incident_question(example_event(), q, llm_complete=lambda _: "invalid json")
        self.assertTrue(fallback_res["fallback_used"])
        self.assertFalse(fallback_res["llm_used"])
        self.assertIn("Hypothetical analysis", fallback_res["answer"])
        self.assertEqual(fallback_res["uncertainty_status"], "hypothetical_reasoning")

    def test_configured_provider_adapter_marks_success_only_after_nonempty_reply(self):
        from unittest.mock import MagicMock, patch
        import llm_provider

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"answer":"Grounded answer."}'}]}}]
        }
        previous_verification = llm_provider._verified_provider
        try:
            llm_provider._verified_provider = None
            with patch.dict(os.environ, {
                "OPSLENS_LLM_PROVIDER": "gemini",
                "OPSLENS_LLM_MODEL": "gemini-test-model",
                "GEMINI_API_KEY": "unit-test-secret",
            }, clear=True), patch("llm_provider.requests.post", return_value=response) as post:
                self.assertFalse(llm_provider.provider_status()["verified"])
                self.assertEqual(llm_provider.complete_chat("grounded prompt"), '{"answer":"Grounded answer."}')
                self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "unit-test-secret")
                self.assertTrue(llm_provider.provider_status()["verified"])
                self.assertEqual(llm_provider.provider_status()["model"], "gemini-test-model")
        finally:
            llm_provider._verified_provider = previous_verification

    def test_groq_provider_uses_env_secret_and_json_chat_completion(self):
        from unittest.mock import MagicMock, patch
        import llm_provider

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": '{"answer":"Grounded Groq answer."}'}}]
        }
        previous_verification = llm_provider._verified_provider
        try:
            llm_provider._verified_provider = None
            with patch.dict(os.environ, {
                "OPSLENS_LLM_PROVIDER": "groq",
                "GROQ_API_KEY": "unit-test-secret",
            }, clear=True), patch("llm_provider.requests.post", return_value=response) as post:
                self.assertEqual(llm_provider.llm_model(), "openai/gpt-oss-20b")
                self.assertEqual(llm_provider.complete_chat("grounded prompt"), '{"answer":"Grounded Groq answer."}')
                self.assertEqual(post.call_args.args[0], "https://api.groq.com/openai/v1/chat/completions")
                self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer unit-test-secret")
                self.assertEqual(post.call_args.kwargs["json"]["response_format"], {"type": "json_object"})
                self.assertTrue(llm_provider.provider_status()["verified"])
        finally:
            llm_provider._verified_provider = previous_verification

    def test_groq_missing_key_and_http_errors_are_safe(self):
        from unittest.mock import MagicMock, patch
        from llm_provider import ProviderError, complete_chat, configuration_error

        with patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "groq"}, clear=True):
            self.assertEqual(configuration_error(), "OPSLENS_LLM_PROVIDER=groq but GROQ_API_KEY is not set.")
            from llm_provider import provider_status
            self.assertEqual(provider_status()["initialization"], "missing_credentials")
            with self.assertRaises(ProviderError) as missing:
                complete_chat("question")
            self.assertEqual(missing.exception.kind, "configuration")
            fallback = answer_incident_question(
                example_event(), "What changed before this alarm?", llm_complete=complete_chat
            )
            self.assertTrue(fallback["fallback_used"])
            self.assertFalse(fallback["llm_used"])
            self.assertEqual(fallback["fallback_reason"], "configuration")
            self.assertEqual(fallback["provider_metadata"]["used_provider"], "deterministic")

        response = MagicMock(status_code=401)
        with patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "groq", "GROQ_API_KEY": "fake"}), \
             patch("llm_provider.requests.post", return_value=response):
            with self.assertRaises(ProviderError) as unauthorized:
                complete_chat("question")
            self.assertEqual(unauthorized.exception.kind, "auth")

    def test_groq_stream_yields_content_and_marks_provider_verified(self):
        from unittest.mock import MagicMock, patch
        import llm_provider

        response = MagicMock(status_code=200)
        response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"Part 1 "}}]}',
            'data: {"choices":[{"delta":{"content":"Part 2"}}]}',
            "data: [DONE]",
        ]
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        previous_verification = llm_provider._verified_provider
        try:
            llm_provider._verified_provider = None
            with patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "groq", "GROQ_API_KEY": "fake"}), \
                 patch("llm_provider.requests.post", return_value=response):
                self.assertEqual(list(llm_provider.stream_chat("prompt")), ["Part 1 ", "Part 2"])
                self.assertTrue(llm_provider.provider_status()["verified"])
        finally:
            llm_provider._verified_provider = previous_verification

    def test_groq_classifies_timeout_bad_json_and_invalid_request(self):
        from unittest.mock import MagicMock, patch
        import requests
        from llm_provider import ProviderError, complete_chat

        env = {"OPSLENS_LLM_PROVIDER": "groq", "GROQ_API_KEY": "fake"}
        with patch.dict(os.environ, env):
            with patch("llm_provider.requests.post", side_effect=requests.exceptions.Timeout()):
                with self.assertRaises(ProviderError) as timeout:
                    complete_chat("question")
                self.assertEqual(timeout.exception.kind, "timeout")

            bad_json = MagicMock(status_code=200)
            bad_json.json.side_effect = ValueError("invalid JSON")
            with patch("llm_provider.requests.post", return_value=bad_json):
                with self.assertRaises(ProviderError) as malformed:
                    complete_chat("question")
                self.assertEqual(malformed.exception.kind, "malformed_response")

            invalid_model = MagicMock(status_code=400)
            with patch("llm_provider.requests.post", return_value=invalid_model):
                with self.assertRaises(ProviderError) as invalid:
                    complete_chat("question")
                self.assertEqual(invalid.exception.kind, "invalid_request")
                self.assertEqual(invalid.exception.status_code, 400)

    def test_groq_429_retries_once_within_budget_and_skips_exhausted_quota(self):
        from unittest.mock import MagicMock, patch
        from llm_provider import ProviderError, complete_chat

        rate_limited = MagicMock(status_code=429, headers={"retry-after": "0.1"})
        rate_limited.json.return_value = {"error": {"message": "rate limit"}}
        recovered = MagicMock(status_code=200)
        recovered.json.return_value = {"choices": [{"message": {"content": '{"answer":"ok"}'}}]}
        with patch.dict(os.environ, {
            "OPSLENS_LLM_PROVIDER": "groq", "GROQ_API_KEY": "fake",
            "OPSLENS_GROQ_MAX_RETRY_WAIT": "0.5",
        }), patch("llm_provider.requests.post", side_effect=[rate_limited, recovered]) as post, \
             patch("llm_provider.time.sleep") as sleep:
            self.assertEqual(complete_chat("prompt"), '{"answer":"ok"}')
            self.assertEqual(post.call_count, 2)
            sleep.assert_called_once_with(0.1)

        exhausted = MagicMock(status_code=429, headers={})
        exhausted.json.return_value = {"error": {"code": "insufficient_quota"}}
        with patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "groq", "GROQ_API_KEY": "fake"}), \
             patch("llm_provider.requests.post", return_value=exhausted) as post, \
             patch("llm_provider.time.sleep") as sleep:
            with self.assertRaises(ProviderError) as raised:
                complete_chat("prompt")
            self.assertEqual(raised.exception.kind, "rate_limit")
            post.assert_called_once()
            sleep.assert_not_called()

    def test_transport_errors_are_classified_without_logging_secrets(self):
        import requests
        from llm_provider import _request_failure_kind

        self.assertEqual(_request_failure_kind(requests.exceptions.SSLError("certificate failure")), "tls_error")
        self.assertEqual(_request_failure_kind(requests.exceptions.ProxyError("proxy refused")), "proxy_error")
        self.assertEqual(_request_failure_kind(requests.exceptions.ConnectTimeout()), "connection_timeout")
        dns_cause = OSError("getaddrinfo failed")
        connection = requests.exceptions.ConnectionError("transport failure")
        connection.__cause__ = dns_cause
        self.assertEqual(_request_failure_kind(connection), "dns_error")

    def test_unverified_sop_does_not_bypass_llm_but_cannot_become_instructions(self):
        event = example_event()
        event["sop_match"] = {
            "sop_id": "SOP-TEST-UNVERIFIED",
            "document_status": "Approval status not verified",
            "retrieved_chunks": [{"payload": {
                "sop_id": "SOP-TEST-UNVERIFIED",
                "document_name": "Pump procedure reference",
                "section": "3.2",
                "document_status": "Approval status not verified",
                "text": "Inspect the recorded pump condition before taking further action.",
            }}],
        }
        called = []
        safe_answer = (
            "The recorded event story shows a flow reduction before the high-pressure alarm. The time window has a "
            "recorded-data gap; this is a temporal association, not proof of physical cause. The retrieved procedure "
            "is an unverified reference; sufficient approved guidance was not retrieved."
        )
        context = {"missing_data": ["No numeric readings were recorded during the first 25 minutes."],
                   "trend_summaries": [{"tag": "FIT-02-FLW", "unit": "L/min", "first_observed": {"value": 82}, "last_observed": {"value": 56}}]}
        result = answer_incident_question(
            event, "What changed in the readings and what SOP applies?",
            llm_complete=lambda prompt: called.append(prompt) or json.dumps({"answer": safe_answer}),
            context=context,
            sop_document_loader=lambda _sop_id: {
                "sop_id": "SOP-TEST-UNVERIFIED", "title": "Pump procedure reference",
                "equipment_id": "Pump-02", "steps": ["Inspect the recorded pump condition before taking further action."],
            },
        )
        self.assertEqual(len(called), 1)
        self.assertIn("Approval status not verified", called[0])
        self.assertIn("Inspect the recorded pump condition", called[0])
        self.assertIn("reference_only_not_approved", called[0])
        self.assertTrue(result["llm_used"])
        self.assertFalse(result["fallback_used"])
        self.assertIsNone(result["fallback_reason"])
        self.assertEqual(result["uncertainty_status"], "insufficient_approved_procedure")
        self.assertIn("approval status is not verified", result["answer"].lower())
        self.assertIn("flow reduction", result["answer"].lower())
        self.assertIn("no numeric readings were recorded", result["answer"].lower())
        self.assertEqual(result["sources"][0]["document_status"], "Approval status not verified")

    def test_unverified_reference_is_descriptively_summarized_and_never_used_as_action(self):
        event = example_event()
        event["sop_match"] = {
            "sop_id": "SOP-TEST-UNVERIFIED",
            "retrieved_chunks": [{"payload": {
                "sop_id": "SOP-TEST-UNVERIFIED", "section": "3.2",
                "text": "Inspect the recorded pump condition before taking further action.",
            }}],
        }
        answer_text = (
            "The reference-only passage in SOP-TEST-UNVERIFIED, Section 3.2, describes reviewing "
            "the recorded pump condition; its approval is not verified, so approved guidance was not retrieved."
        )
        result = answer_incident_question(
            event, "What does the retrieved procedure cover?",
            llm_complete=lambda _prompt: json.dumps({
                "answer": answer_text,
                "immediate_checks": ["Isolate the pump immediately."],
            }),
            sop_document_loader=lambda _sop_id: {
                "sop_id": "SOP-TEST-UNVERIFIED", "title": "Pump procedure reference",
                "equipment_id": "Pump-02",
                "steps": ["Inspect the recorded pump condition before taking further action."],
            },
        )
        self.assertTrue(result["llm_used"])
        self.assertIn("reference-only passage", result["answer"].lower())
        self.assertIn("REFERENCE ONLY — NOT APPROVED", result["answer"])
        self.assertNotIn("Isolate the pump", result["answer"])
        self.assertNotIn("Isolate the pump", result["operator_response"]["recommended_checks"])
        self.assertEqual(result["operator_response"]["relevant_sop"]["passages"][0]["text"],
                         "Inspect the recorded pump condition before taking further action.")
        self.assertEqual(result["operator_response"]["resolution_criteria"],
                         "Not established by retrieved approved guidance.")

    def test_unverified_sop_instructions_from_llm_are_rejected(self):
        event = example_event()
        event["sop_match"] = {
            "sop_id": "SOP-TEST-UNVERIFIED",
            "document_status": "Approval status not verified",
            "retrieved_chunks": [{"payload": {
                "sop_id": "SOP-TEST-UNVERIFIED",
                "document_name": "Pump procedure reference",
                "section": "3.2",
                "document_status": "Approval status not verified",
                "text": "Inspect the recorded pump condition before taking further action.",
            }}],
        }
        result = answer_incident_question(
            event, "What SOP applies to this incident?",
            llm_complete=lambda _prompt: '{"answer":"First, isolate the pump before inspection."}',
            sop_document_loader=lambda _sop_id: {
                "sop_id": "SOP-TEST-UNVERIFIED", "title": "Pump procedure reference",
                "equipment_id": "Pump-02", "steps": ["Inspect the recorded pump condition before taking further action."],
            },
        )
        self.assertFalse(result["llm_used"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fallback_reason"], "unverified_sop_actionable_language")
        self.assertIn("approval status is not verified", result["answer"].lower())

    def test_unapproved_sop_threshold_cannot_ground_model_numeric_claim(self):
        event = example_event()
        event["sop_match"] = {
            "sop_id": "SOP-TEST-UNVERIFIED",
            "retrieved_chunks": [{"payload": {
                "sop_id": "SOP-TEST-UNVERIFIED", "section": "3.2",
                "text": "Keep the valve below 70% during this procedure.",
            }}],
        }
        result = answer_incident_question(
            event, "What does the reference say?",
            llm_complete=lambda _prompt: json.dumps({
                "answer": "The reference says the valve should remain below 70%."
            }),
            sop_document_loader=lambda _sop_id: {
                "sop_id": "SOP-TEST-UNVERIFIED", "title": "Unapproved reference",
                "equipment_id": "Pump-02", "steps": ["Keep the valve below 70% during this procedure."],
            },
        )
        self.assertFalse(result["llm_used"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fallback_reason"], "ungrounded_numeric_value")
        self.assertIn("REFERENCE ONLY — NOT APPROVED", result["answer"])

    def test_ungrounded_numeric_draft_gets_one_correction_attempt(self):
        drafts = iter([
            '{"answer":"Flow changed by 999.1 L/min; this implies a mechanism not recorded."}',
            '{"answer":"Recorded flow fell from 82 to 56 L/min. This is a historical association, not proof of cause."}',
        ])
        prompts = []

        def fake_llm(prompt):
            prompts.append(prompt)
            return next(drafts)

        result = answer_incident_question(
            example_event(), "What changed in the flow before the alarm?", llm_complete=fake_llm
        )
        self.assertEqual(len(prompts), 2)
        self.assertIn("CORRECTION REQUIRED", prompts[1])
        self.assertTrue(result["llm_used"])
        self.assertFalse(result["fallback_used"])
        self.assertIn("82 to 56", result["answer"])
        self.assertNotIn("999.1 L/min", result["answer"])

    def test_failed_grounding_correction_preserves_primary_fallback_reason(self):
        from llm_provider import ProviderError

        calls = 0

        def fake_llm(_prompt):
            nonlocal calls
            calls += 1
            if calls == 1:
                return '{"answer":"Flow changed by 999.1 L/min."}'
            raise ProviderError("rate_limit", "provider throttled correction")

        result = answer_incident_question(
            example_event(), "What changed in the flow readings?", llm_complete=fake_llm
        )
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fallback_reason"], "ungrounded_numeric_value")
        self.assertEqual(result["correction_failure_reason"], "rate_limit")
        self.assertEqual(result["provider_metadata"]["correction_failure_reason"], "rate_limit")

    def test_api_response_preserves_top_level_and_nested_correction_failure_metadata(self):
        from llm_provider import ProviderError

        calls = 0

        def fake_llm(_prompt):
            nonlocal calls
            calls += 1
            if calls == 1:
                return '{"answer":"FIT-02-FLW reached 999.1 L/min."}'
            raise ProviderError("rate_limit", "provider throttled correction")

        assistant._llm_complete_override = fake_llm
        client = TestClient(create_app(orchestrator=FakeOrchestrator()))
        response = client.post("/api/assistant/ask", json={
            "event_id": "incident-1", "question": "What changed in the flow readings?",
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(calls, 2)
        self.assertTrue(data["fallback_used"])
        self.assertFalse(data["llm_used"])
        self.assertEqual(data["fallback_reason"], "ungrounded_numeric_value")
        self.assertEqual(data["correction_failure_reason"], "rate_limit")
        self.assertEqual(data["provider_metadata"]["correction_failure_reason"], "rate_limit")
        self.assertIn("supporting_readings", data)

    def test_signed_trend_change_may_be_reported_as_rounded_magnitude(self):
        result = answer_incident_question(
            example_event(),
            "What changed in flow before the alarm?",
            context={"trend_summaries": [{
                "tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 38,
                "first_observed": {"value": 82.39, "timestamp": "2026-10-17T06:21:06Z"},
                "last_observed": {"value": 56, "timestamp": "2026-10-17T06:22:20Z"},
                "absolute_change": -26.39, "percentage_change": -32.030586,
            }]},
            llm_complete=lambda _prompt: '{"answer":"Flow fell from 82.39 to 56 L/min, a 26.39 L/min drop (32.0%)."}',
        )
        self.assertTrue(result["llm_used"])
        self.assertIn("32.0%", result["answer"])

        precise = answer_incident_question(
            example_event(), "What changed in flow before the alarm?",
            context={"trend_summaries": [{"tag": "FIT-02-FLW", "unit": "L/min",
                "reading_count": 2, "first_observed": {"value": 82.39, "timestamp": "2026-10-17T06:21:06Z"},
                "last_observed": {"value": 56, "timestamp": "2026-10-17T06:22:20Z"},
                "absolute_change": -26.39, "percentage_change": -32.03058623619371}]},
            llm_complete=lambda _prompt: '{"answer":"FIT-02-FLW fell by 32.03058623619371%."}',
        )
        self.assertTrue(precise["llm_used"])

    def test_timestamp_components_do_not_count_as_measurement_numbers(self):
        from assistant import _allowed_numbers

        allowed = _allowed_numbers({
            "timestamp": "2026-10-17T06:21:10.867915Z",
            "recorded_value": 82.39,
        })
        self.assertIn(82.39, allowed)
        self.assertNotIn(10.0, allowed)
        self.assertNotIn(-10.0, allowed)
        self.assertNotIn(2026.0, allowed)
        self.assertNotIn(17.0, allowed)

    def test_date_only_iso_fragment_is_not_checked_as_a_measurement(self):
        context = {"trend_summaries": [{
            "tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
            "first_observed": {"value": 82.39, "timestamp": "2026-10-17T06:21:06Z"},
            "last_observed": {"value": 56, "timestamp": "2026-10-17T06:22:20Z"},
            "absolute_change": -26.39, "percentage_change": -32.030586,
        }]}
        result = answer_incident_question(
            example_event(), "What changed in the flow?", context=context,
            llm_complete=lambda _prompt: (
                '{"answer":"FIT-02-FLW fell from 82.39 to 56 L/min on 2026-10-17, '
                'a 32.0% decrease."}'
            ),
        )
        self.assertTrue(result["llm_used"])

    def test_date_components_are_not_allowed_as_free_standing_sensor_values(self):
        context = {"trend_summaries": [{
            "tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
            "first_observed": {"value": 82.39, "timestamp": "2026-10-17T06:21:06Z"},
            "last_observed": {"value": 56, "timestamp": "2026-10-17T06:22:20Z"},
            "absolute_change": -26.39, "percentage_change": -32.030586,
        }]}
        result = answer_incident_question(
            example_event(), "What changed in the flow?", context=context,
            llm_complete=lambda _prompt: '{"answer":"FIT-02-FLW was 10 L/min."}',
        )
        self.assertFalse(result["llm_used"])
        self.assertEqual(result["fallback_reason"], "ungrounded_numeric_value")

    def test_recorded_clock_fragment_is_not_rejected_as_sensor_value(self):
        context = {"trend_summaries": [{
            "tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
            "first_observed": {"value": 82.39, "timestamp": "2026-10-17T10:30:00Z"},
            "last_observed": {"value": 56, "timestamp": "2026-10-17T10:31:00Z"},
            "absolute_change": -26.39, "percentage_change": -32.030586,
        }]}
        result = answer_incident_question(
            example_event(), "What happened around 10:30?", context=context,
            llm_complete=lambda _prompt: '{"answer":"At 10:30 FIT-02-FLW was 82.39 L/min."}',
        )
        self.assertTrue(result["llm_used"])

        unrecorded = answer_incident_question(
            example_event(), "What happened?", context=context,
            llm_complete=lambda _prompt: '{"answer":"At 10:45 FIT-02-FLW was 82.39 L/min."}',
        )
        self.assertFalse(unrecorded["llm_used"])
        self.assertEqual(unrecorded["fallback_reason"], "ungrounded_timestamp")

    def test_recorded_context_window_duration_is_not_misattributed_to_a_tag(self):
        context = {
            "window": {"start": "2026-10-17T10:00:00Z", "end": "2026-10-17T10:30:00Z", "duration_minutes": 30},
            "trend_summaries": [{
                "tag": "MOT-02-CUR", "unit": "A", "reading_count": 2,
                "first_observed": {"value": 7.4, "timestamp": "2026-10-17T10:29:00Z"},
                "last_observed": {"value": 9.2, "timestamp": "2026-10-17T10:30:00Z"},
                "absolute_change": 1.8, "percentage_change": 24.3,
            }],
        }
        accepted = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"MOT-02-CUR changed during the 30-minute context window."}',
        )
        self.assertTrue(accepted["llm_used"])

        unsupported_duration = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"MOT-02-CUR changed during the 10-minute context window."}',
        )
        self.assertFalse(unsupported_duration["llm_used"])
        self.assertEqual(unsupported_duration["fallback_reason"], "ungrounded_numeric_value")

        mismatched_window = {
            **context,
            "window": {"start": "2026-10-17T10:10:00Z", "end": "2026-10-17T10:30:00Z", "duration_minutes": 30},
        }
        mismatch_result = answer_incident_question(
            example_event(), "What changed?", context=mismatched_window,
            llm_complete=lambda _prompt: '{"answer":"MOT-02-CUR changed during the 30-minute context window."}',
        )
        self.assertFalse(mismatch_result["llm_used"])
        self.assertEqual(mismatch_result["fallback_reason"], "ungrounded_numeric_value")

        tag_duration = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"MOT-02-CUR was 30 minutes."}',
        )
        self.assertFalse(tag_duration["llm_used"])
        self.assertEqual(tag_duration["fallback_reason"], "ungrounded_numeric_value")

        duration_attached_to_tag = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: (
                '{"answer":"MOT-02-CUR was 30 minutes during the context window."}'
            ),
        )
        self.assertFalse(duration_attached_to_tag["llm_used"])
        self.assertEqual(duration_attached_to_tag["fallback_reason"], "ungrounded_numeric_value")

        unsupported_reading = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"MOT-02-CUR reached 30 A."}',
        )
        self.assertFalse(unsupported_reading["llm_used"])
        self.assertEqual(unsupported_reading["fallback_reason"], "ungrounded_numeric_value")

    def test_trend_prompt_omits_unrequested_context_duration(self):
        captured = {}
        context = {
            "window": {"start": "2026-10-17T10:00:00Z", "end": "2026-10-17T10:30:00Z", "duration_minutes": 30},
            "trend_summaries": [],
        }

        def fake_llm(prompt):
            captured["prompt"] = prompt
            return '{"answer":"The available readings show a change, with data coverage limitations."}'

        result = answer_incident_question(
            example_event(), "What changed in the context window?", context=context,
            llm_complete=fake_llm,
        )
        self.assertTrue(result["llm_used"])
        self.assertIn("Do not state the numeric context-window duration unless the operator asks", captured["prompt"])

    def test_numeric_rejection_log_identifies_claim_without_logging_sentence(self):
        with self.assertLogs("opslens.assistant", level="WARNING") as captured:
            result = answer_incident_question(
                example_event(), "private operator question text",
                context={"trend_summaries": [{
                    "tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
                    "first_observed": {"value": 82.39, "timestamp": "2026-10-17T10:30:00Z"},
                    "last_observed": {"value": 56, "timestamp": "2026-10-17T10:31:00Z"},
                    "absolute_change": -26.39, "percentage_change": -32.030586,
                }]},
                llm_complete=lambda _prompt: '{"answer":"FIT-02-FLW was 10 L/min; private generated text."}',
            )
        self.assertEqual(result["fallback_reason"], "ungrounded_numeric_value")
        log = "\n".join(captured.output)
        self.assertIn("token=10", log)
        self.assertIn("tag_scope=FIT-02-FLW", log)
        self.assertIn("reason=ungrounded_numeric_value", log)
        self.assertNotIn("private operator question", log)
        self.assertNotIn("private generated text", log)

    def test_value_from_another_tag_cannot_support_tagged_numeric_claim(self):
        context = {"trend_summaries": [
            {"tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
             "first_observed": {"value": 82.39, "timestamp": "2026-10-17T06:21:06Z"},
             "last_observed": {"value": 56, "timestamp": "2026-10-17T06:22:20Z"},
             "absolute_change": -26.39, "percentage_change": -32.030586},
            {"tag": "MOT-02-CUR", "unit": "A", "reading_count": 2,
             "first_observed": {"value": 7.55, "timestamp": "2026-10-17T06:21:06Z"},
             "last_observed": {"value": 9.2, "timestamp": "2026-10-17T06:22:20Z"},
             "absolute_change": 1.65, "percentage_change": 21.8543},
        ]}
        result = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"FIT-02-FLW was 9.2 L/min."}',
        )
        self.assertFalse(result["llm_used"])
        self.assertEqual(result["fallback_reason"], "ungrounded_numeric_value")

    def test_negative_percentage_sign_is_preserved_for_tagged_change(self):
        context = {"trend_summaries": [{
            "tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
            "first_observed": {"value": 82.39, "timestamp": "2026-10-17T06:21:06Z"},
            "last_observed": {"value": 56, "timestamp": "2026-10-17T06:22:20Z"},
            "absolute_change": -26.39, "percentage_change": -32.030586,
        }]}
        valid = answer_incident_question(
            example_event(), "What changed in the flow?", context=context,
            llm_complete=lambda _prompt: '{"answer":"FIT-02-FLW change was -32.0%."}',
        )
        self.assertTrue(valid["llm_used"])
        wrong_sign = answer_incident_question(
            example_event(), "What changed in the flow?", context=context,
            llm_complete=lambda _prompt: '{"answer":"FIT-02-FLW fell by +32.0%."}',
        )
        self.assertFalse(wrong_sign["llm_used"])
        self.assertEqual(wrong_sign["fallback_reason"], "ungrounded_numeric_value")

    def test_typed_valve_change_accepts_rounded_percentage_points_only(self):
        context = {"trend_summaries": [{
            "tag": "VLV-04-POS", "unit": "%", "reading_count": 4,
            "first_observed": {"value": 75.52, "timestamp": "2026-10-17T10:00:00Z"},
            "last_observed": {"value": 43.0, "timestamp": "2026-10-17T10:30:00Z"},
            "absolute_change": -32.52, "percentage_change": -43.06144,
        }]}
        accepted = answer_incident_question(
            example_event(), "What changed in valve position?", context=context,
            llm_complete=lambda _prompt: '{"answer":"VLV-04-POS fell by 32.5 percentage points."}',
        )
        self.assertTrue(accepted["llm_used"])
        self.assertFalse(accepted["fallback_used"])

        ambiguous = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"The change was 32.5."}',
        )
        self.assertFalse(ambiguous["llm_used"])
        self.assertTrue(ambiguous["fallback_used"])
        self.assertEqual(ambiguous["fallback_reason"], "ungrounded_numeric_value")

    def test_compact_numeric_facts_keep_type_units_and_source_timestamps(self):
        compact = assistant.compact_llm_context(
            example_event(),
            {"window": {"start": "2026-10-17T10:00:00Z", "end": "2026-10-17T10:30:00Z", "duration_minutes": 30},
             "trend_summaries": [{
                 "tag": "VLV-04-POS", "unit": "%", "reading_count": 2,
                 "first_observed": {"value": 75.52, "timestamp": "2026-10-17T10:00:00Z"},
                 "last_observed": {"value": 43, "timestamp": "2026-10-17T10:30:00Z"},
                 "absolute_change": -32.52, "percentage_change": -43.06144,
             }]},
            {},
        )
        facts = compact["numeric_facts"]
        pp = next(fact for fact in facts if fact["metric"] == "absolute_change")
        relative = next(fact for fact in facts if fact["metric"] == "percentage_change")
        duration = next(fact for fact in facts if fact["metric"] == "context_window_duration")
        for fact in (pp, relative, duration):
            self.assertTrue({"tag", "metric", "exact_value", "unit", "change_type", "timestamps"}.issubset(fact))
        self.assertEqual((pp["exact_value"], pp["unit"], pp["change_type"]), (-32.52, "percentage points", "percentage_point_change"))
        self.assertEqual((relative["exact_value"], relative["unit"], relative["change_type"]), (-43.06144, "%", "relative_percentage_change"))
        self.assertEqual(duration["timestamps"], ["2026-10-17T10:00:00Z", "2026-10-17T10:30:00Z"])

    def test_recorded_reading_counts_and_coverage_are_typed_grounded_facts(self):
        context = {"window": {"start": "2026-10-17T10:00:00Z", "end": "2026-10-17T10:30:00Z", "duration_minutes": 30},
                   "trend_summaries": [{
                       "tag": "VLV-04-POS", "unit": "%", "reading_count": 38,
                       "first_observed": {"value": 75.52, "timestamp": "2026-10-17T10:29:29Z"},
                       "last_observed": {"value": 43.0, "timestamp": "2026-10-17T10:30:00Z"},
                       "absolute_change": -32.52, "percentage_change": -43.06144,
                       "observed_coverage_seconds": 31.0,
                       "leading_unobserved_seconds": 1769.0,
                       "trailing_unobserved_seconds": 0.0,
                       "coverage_note": "Numeric readings span 31 seconds inside the requested window; no numeric reading was recorded during the first 1769 seconds.",
                   }]}
        grounded = build_assistant_response(example_event(), "What changed?", context=context)
        compact = assistant.compact_llm_context(example_event(), context, grounded)
        facts = compact["numeric_facts"]
        self.assertTrue(any(f["metric"] == "reading_count" and f["exact_value"] == 38 and f["tag"] == "VLV-04-POS" for f in facts))
        self.assertTrue(any(f["metric"] == "observed_coverage_seconds" and f["exact_value"] == 31 for f in facts))
        self.assertTrue(any(f["metric"] == "leading_unobserved_seconds" and f["exact_value"] == 1769 for f in facts))
        self.assertIn("VLV-04-POS: Numeric readings span", grounded["answer"])

        # Rephrasing the exact deterministic trend facts must not fail because
        # counts and coverage durations were only present in prose.
        result = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: json.dumps({
                "answer": "VLV-04-POS had 38 recorded readings; VLV-04-POS had no numeric readings in the first 1769 seconds."
            }),
        )
        self.assertTrue(result["llm_used"])
        self.assertFalse(result["fallback_used"])

        unsupported = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"VLV-04-POS reached 999% and had 38 L/min readings."}',
        )
        self.assertFalse(unsupported["llm_used"])
        self.assertEqual(unsupported["fallback_reason"], "ungrounded_numeric_value")

    def test_percentage_points_and_relative_percent_are_not_interchangeable(self):
        context = {"trend_summaries": [{
            "tag": "VLV-04-POS", "unit": "%", "reading_count": 2,
            "first_observed": {"value": 75.52, "timestamp": "2026-10-17T10:00:00Z"},
            "last_observed": {"value": 43.0, "timestamp": "2026-10-17T10:30:00Z"},
            "absolute_change": -32.52, "percentage_change": -43.06144,
        }]}
        valid_relative = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"VLV-04-POS fell by 43.1% relative to its first reading."}',
        )
        self.assertTrue(valid_relative["llm_used"])
        wrong_relative = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"VLV-04-POS fell by 32.5% relative to its first reading."}',
        )
        self.assertFalse(wrong_relative["llm_used"])
        wrong_points = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"VLV-04-POS fell by 43.1 percentage points."}',
        )
        self.assertFalse(wrong_points["llm_used"])

    def test_physical_change_rounding_requires_the_correct_engineering_unit(self):
        context = {"trend_summaries": [
            {"tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
             "first_observed": {"value": 82.39, "timestamp": "2026-10-17T10:00:00Z"},
             "last_observed": {"value": 56.0, "timestamp": "2026-10-17T10:30:00Z"},
             "absolute_change": -26.39, "percentage_change": -32.0308},
            {"tag": "MOT-02-CUR", "unit": "A", "reading_count": 2,
             "first_observed": {"value": 7.39, "timestamp": "2026-10-17T10:00:00Z"},
             "last_observed": {"value": 9.2, "timestamp": "2026-10-17T10:30:00Z"},
             "absolute_change": 1.81, "percentage_change": 24.4926},
            {"tag": "PIT-02-PRS", "unit": "bar", "reading_count": 2,
             "first_observed": {"value": 4.69, "timestamp": "2026-10-17T10:00:00Z"},
             "last_observed": {"value": 6.9, "timestamp": "2026-10-17T10:30:00Z"},
             "absolute_change": 2.21, "percentage_change": 47.1215},
        ]}
        for answer in (
            "FIT-02-FLW fell by 26.4 L/min.",
            "MOT-02-CUR rose by 1.8 A.",
            "PIT-02-PRS rose by 2.2 bar.",
        ):
            with self.subTest(answer=answer):
                result = answer_incident_question(
                    example_event(), "What changed?", context=context,
                    llm_complete=lambda _prompt, text=answer: json.dumps({"answer": text}),
                )
                self.assertTrue(result["llm_used"])
        wrong_unit = answer_incident_question(
            example_event(), "What changed?", context=context,
            llm_complete=lambda _prompt: '{"answer":"PIT-02-PRS rose by 2.2 A."}',
        )
        self.assertFalse(wrong_unit["llm_used"])

    def test_compound_open_ended_trend_answer_scopes_values_to_nearest_tag(self):
        context = {"trend_summaries": [
            {"tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
             "first_observed": {"value": 82.39, "timestamp": "2026-10-17T10:00:00Z"},
             "last_observed": {"value": 56.0, "timestamp": "2026-10-17T10:30:00Z"},
             "absolute_change": -26.39, "percentage_change": -32.0308},
            {"tag": "MOT-02-CUR", "unit": "A", "reading_count": 2,
             "first_observed": {"value": 7.39, "timestamp": "2026-10-17T10:00:00Z"},
             "last_observed": {"value": 9.2, "timestamp": "2026-10-17T10:30:00Z"},
             "absolute_change": 1.81, "percentage_change": 24.4926},
        ]}
        result = answer_incident_question(
            example_event(), "Could you compare flow and motor current before the alarm?",
            context=context,
            llm_complete=lambda _prompt: json.dumps({
                "answer": "FIT-02-FLW fell by 26.4 L/min while MOT-02-CUR rose by 1.8 A."
            }),
        )
        self.assertTrue(result["llm_used"])
        self.assertFalse(result["fallback_used"])

        mismatched = answer_incident_question(
            example_event(), "Could you compare flow and motor current before the alarm?",
            context=context,
            llm_complete=lambda _prompt: json.dumps({
                "answer": "FIT-02-FLW fell by 1.8 A while MOT-02-CUR rose by 26.4 L/min."
            }),
        )
        self.assertFalse(mismatched["llm_used"])
        self.assertEqual(mismatched["fallback_reason"], "ungrounded_numeric_value")

    def test_open_ended_question_and_relevant_context_are_sent_to_llm(self):
        captured = {}
        context = {
            "window": {"start": "2026-10-17T10:00:00Z", "end": "2026-10-17T10:30:00Z", "duration_minutes": 30},
            "topology": {"equipment_id": "Pump-02", "relevant_tags": ["FIT-02-FLW"],
                         "interpretation": "Configured equipment relationships; not causal evidence."},
            "data_sources": ["SQLite.tag_readings", "SQLite.operator_actions"],
            "operator_actions": [{"action_id": "audit-1", "event_id": "event-1", "action_type": "inspection",
                                   "operator": "Operator A", "timestamp_utc": "2026-10-17T10:20:00Z",
                                   "notes": "Recorded visual check"}],
            "trend_summaries": [{"tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
                                 "first_observed": {"value": 82, "timestamp": "2026-10-17T10:01:00Z"},
                                 "last_observed": {"value": 56, "timestamp": "2026-10-17T10:29:00Z"},
                                 "absolute_change": -26, "percentage_change": -31.7}],
        }
        question = "Did a recorded operator action happen before flow dropped, and what can topology tell us?"

        def fake_llm(prompt):
            captured["prompt"] = prompt
            return json.dumps({"answer": "I found the available flow readings and the recorded inspection action. The topology is configured relationship context, not proof of cause."})

        result = answer_incident_question(example_event(), question, context=context, llm_complete=fake_llm)
        self.assertTrue(result["llm_used"])
        prompt = captured["prompt"]
        self.assertIn(question, prompt)
        self.assertIn("topology", prompt)
        self.assertIn("Recorded visual check", prompt)
        self.assertIn("open-ended natural-language questions", prompt)

    def test_structured_context_duration_requires_matching_timestamps_and_framing(self):
        context = {"window": {"start": "2026-10-17T10:00:00Z", "end": "2026-10-17T10:30:00Z", "duration_minutes": 30},
                   "trend_summaries": []}
        valid = answer_incident_question(
            example_event(), "Summarize the window", context=context,
            llm_complete=lambda _prompt: '{"answer":"The context window covers 30 minutes."}',
        )
        self.assertTrue(valid["llm_used"])
        ambiguous = answer_incident_question(
            example_event(), "Summarize the window", context=context,
            llm_complete=lambda _prompt: '{"answer":"The change was 30."}',
        )
        self.assertFalse(ambiguous["llm_used"])
        self.assertEqual(ambiguous["fallback_reason"], "ungrounded_numeric_value")
        unsupported_sensor = answer_incident_question(
            example_event(), "Summarize the window", context={
                **context,
                "trend_summaries": [{
                    "tag": "MOT-02-CUR", "unit": "A", "reading_count": 2,
                    "first_observed": {"value": 7.4, "timestamp": "2026-10-17T10:29:00Z"},
                    "last_observed": {"value": 9.2, "timestamp": "2026-10-17T10:30:00Z"},
                    "absolute_change": 1.8, "percentage_change": 24.3,
                }],
            },
            llm_complete=lambda _prompt: '{"answer":"MOT-02-CUR reached 30 A."}',
        )
        self.assertFalse(unsupported_sensor["llm_used"])
        self.assertEqual(unsupported_sensor["fallback_reason"], "ungrounded_numeric_value")
        for bad_context, answer in (
            ({**context, "window": {"start": "2026-10-17T10:10:00Z", "end": "2026-10-17T10:30:00Z", "duration_minutes": 30}},
             "The 30-minute context window contains the available evidence."),
            (context, "The 31-minute context window contains the available evidence."),
            (context, "The timeline spans 30 minutes."),
        ):
            with self.subTest(answer=answer):
                result = answer_incident_question(
                    example_event(), "Summarize the window", context=bad_context,
                    llm_complete=lambda _prompt, text=answer: json.dumps({"answer": text}),
                )
                self.assertFalse(result["llm_used"])
                self.assertEqual(result["fallback_reason"], "ungrounded_numeric_value")

    def test_llm_timestamps_must_match_recorded_context_exactly(self):
        context = {"trend_summaries": [{
            "tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
            "first_observed": {"value": 82.39, "timestamp": "2026-10-17T06:21:06.867915Z"},
            "last_observed": {"value": 56, "timestamp": "2026-10-17T06:22:20.867915Z"},
            "absolute_change": -26.39, "percentage_change": -32.0,
        }]}
        valid = answer_incident_question(
            example_event(), "What changed in the historical flow readings?", context=context,
            llm_complete=lambda _prompt: (
                '{"answer":"Flow fell from 82.39 to 56 L/min between '
                '2026-10-17T06:21:06.867915Z and 2026-10-17T06:22:20.867915Z."}'
            ),
        )
        self.assertTrue(valid["llm_used"])

        invented = answer_incident_question(
            example_event(), "What changed in the historical flow readings?", context=context,
            llm_complete=lambda _prompt: (
                '{"answer":"Flow fell from 82.39 to 56 L/min at 2099-12-31T23:59:59Z."}'
            ),
        )
        self.assertFalse(invented["llm_used"])
        self.assertEqual(invented["fallback_reason"], "ungrounded_timestamp")

    def test_provider_failure_with_unverified_sop_still_returns_recorded_trends(self):
        from llm_provider import ProviderError

        event = example_event()
        event["sop_match"] = {
            "sop_id": "SOP-TEST-UNVERIFIED",
            "document_status": "Approval status not verified",
            "retrieved_chunks": [],
        }
        context = {"trend_summaries": [{
            "tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 38,
            "first_observed": {"value": 82, "timestamp": "2026-10-17T06:21:06Z"},
            "last_observed": {"value": 56, "timestamp": "2026-10-17T06:22:20Z"},
            "absolute_change": -26, "percentage_change": -31.7,
            "coverage_note": "No numeric readings were recorded during the first 25 minutes.",
        }]}

        def unavailable(_prompt):
            raise ProviderError("connection_error", "provider transport failed")

        result = answer_incident_question(
            event,
            "What changed in the last 30 minutes and what does the SOP say?",
            context=context,
            llm_complete=unavailable,
        )
        self.assertFalse(result["llm_used"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fallback_reason"], "connection_error")
        self.assertIn("FIT-02-FLW:", result["answer"])
        self.assertIn("fell by 26 L/min", result["answer"])
        self.assertIn("82 L/min", result["answer"])
        self.assertIn("56 L/min", result["answer"])
        self.assertIn("first 25 minutes", result["answer"])
        self.assertIn("could not be resolved", result["answer"].lower())

    def test_llm_cannot_change_uncertainty_or_operator_checks(self):
        def fake_llm(_prompt):
            return json.dumps({
                "answer": "The event record is a correlation hypothesis, not a confirmed physical cause.",
                "uncertainty_status": "confirmed_root_cause",
                "immediate_checks": ["Reset the PLC immediately."],
            })

        result = answer_incident_question(example_event(), "Why did this alarm trigger?", llm_complete=fake_llm)
        self.assertTrue(result["llm_used"])
        self.assertEqual(result["uncertainty_status"], "hypothesis_requires_operator_verification")
        self.assertNotIn("Reset the PLC immediately.", result["immediate_checks"])
        self.assertEqual(result["provider_metadata"]["used_provider"], "configured_test_override")

    def test_conversation_isolation_and_follow_up_history_limit(self):
        class TwoEventOrchestrator(FakeOrchestrator):
            def get_full_event(self, event_id):
                if event_id in ("incident-1", "incident-2"):
                    event = example_event()
                    event["event_id"] = event_id
                    return event
                return None

        client = TestClient(create_app(orchestrator=TwoEventOrchestrator()))
        first = client.post("/api/assistant/ask", json={"event_id": "incident-1", "question": "Why did this alarm trigger?"})
        self.assertEqual(first.status_code, 200)
        convo = first.json()["conversation_id"]
        follow = client.post("/api/assistant/ask", json={
            "event_id": "incident-1",
            "question": "What changed before that?",
            "conversation_id": convo,
        })
        self.assertEqual(follow.status_code, 200)
        self.assertEqual(follow.json()["conversation_id"], convo)
        leaked = client.post("/api/assistant/ask", json={
            "event_id": "incident-2",
            "question": "Has this happened on this valve today?",
            "conversation_id": convo,
        })
        self.assertEqual(leaked.status_code, 409)

    def test_streaming_emits_status_then_done(self):
        client = TestClient(create_app(orchestrator=FakeOrchestrator()))
        with client.stream("POST", "/api/assistant/ask/stream", json={"event_id": "incident-1", "question": "Why did this alarm trigger?"}) as response:
            self.assertEqual(response.status_code, 200)
            body = "".join(response.iter_text())
        self.assertIn("event: status", body)
        self.assertIn("event: done", body)
        self.assertIn("not proof of causation", body)

    def test_streaming_metadata_matches_the_answer_generator(self):
        from unittest.mock import patch

        client = TestClient(create_app(orchestrator=FakeOrchestrator()))
        generated = {
            "answer": "The verified test provider returned this grounded response.",
            "uncertainty_status": "hypothesis_requires_operator_verification",
            "llm_used": True,
            "fallback_used": False,
            "fallback_reason": None,
            "supporting_readings": [],
            "supporting_events": [],
            "sources": [],
            "immediate_checks": [],
        }
        with patch("api.routes.answer_incident_question", return_value=generated):
            response = client.post(
                "/api/assistant/ask/stream",
                json={"event_id": "incident-1", "question": "Why did this alarm trigger?"},
            )
        self.assertEqual(response.status_code, 200)
        blocks = [block for block in response.text.split("\n\n") if block.strip()]
        status_payloads = [json.loads(line[6:]) for block in blocks if "event: status" in block
                           for line in block.splitlines() if line.startswith("data: ")]
        done_payloads = [json.loads(line[6:]) for block in blocks if "event: done" in block
                         for line in block.splitlines() if line.startswith("data: ")]
        self.assertTrue(any(item.get("llm_used") is True and item.get("fallback_used") is False for item in status_payloads))
        self.assertTrue(done_payloads[0]["llm_used"])
        self.assertFalse(done_payloads[0]["fallback_used"])

    def test_cache_does_not_reuse_stale_readings(self):
        event = example_event()
        context_a = {"window": {"start": "2026-10-16T09:30:00Z", "end": "2026-10-16T10:00:00Z"},
                     "readings": [{"tag": "FIT-02-FLW", "value": 80, "timestamp": "2026-10-16T09:58:00Z"}]}
        context_b = {"window": {"start": "2026-10-16T09:30:00Z", "end": "2026-10-16T10:00:00Z"},
                     "readings": [{"tag": "FIT-02-FLW", "value": 40, "timestamp": "2026-10-16T09:59:00Z"}]}
        key_a = cache_key("incident-1", "why", context_fingerprint(event, context_a))
        key_b = cache_key("incident-1", "why", context_fingerprint(event, context_b))
        self.assertNotEqual(key_a, key_b)
        put(key_a, {"answer": "old"})
        self.assertEqual(get(key_a)["answer"], "old")
        self.assertIsNone(get(key_b))
        self.assertTrue(question_is_volatile("Has this happened on this valve today?"))

    def test_missing_sop_question_does_not_invent_steps_via_llm(self):
        event = example_event()
        event["sop_match"] = {"sop_id": "SOP-NONE", "retrieved_chunks": []}
        def invent_sop(_prompt):
            return json.dumps({
                "answer": "Open the bypass and increase setpoint to 12.",
                "immediate_checks": ["Open the bypass", "increase setpoint"],
            })
        result = answer_incident_question(event, "What procedure should I follow?", llm_complete=invent_sop)
        self.assertTrue(result["fallback_used"])
        self.assertIn("No applicable approved SOP passage was retrieved", result["answer"])

    def test_missing_sop_does_not_block_llm_evidence_explanation_or_allow_invented_readings(self):
        event = example_event()
        event["sop_match"] = {
            "sop_id": "SOP-NONE", "retrieved_chunks": [], "retrieval_status": "no_match"
        }
        context = {
            "window": {"start": "2026-10-16T09:30:00Z", "end": "2026-10-16T10:00:00Z"},
            "readings": [
                {"tag": "FIT-02-FLW", "value": 82, "unit": "L/min", "timestamp": "2026-10-16T09:58:00Z"},
                {"tag": "FIT-02-FLW", "value": 56, "unit": "L/min", "timestamp": "2026-10-16T09:59:00Z"},
            ],
            "trend_summaries": [{
                "tag": "FIT-02-FLW", "unit": "L/min", "reading_count": 2,
                "first_observed": {"value": 82, "timestamp": "2026-10-16T09:58:00Z"},
                "last_observed": {"value": 56, "timestamp": "2026-10-16T09:59:00Z"},
                "minimum": {"value": 56}, "maximum": {"value": 82},
                "absolute_change": -26, "percentage_change": -31.7,
                "coverage_note": "Partial recorded history.", "gap_count": 0,
            }],
            "related_events": [], "operator_actions": [], "missing_data": [],
        }
        result = answer_incident_question(
            event,
            "What changed in the historical flow readings?",
            context=context,
            llm_complete=lambda _prompt: json.dumps({
                "answer": "FIT-02-FLW fell from 82 to 56 L/min in the recorded readings; this supports an association, not a confirmed cause."
            }),
        )
        self.assertTrue(result["llm_used"])
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["sop_resolution"]["status"], "not_retrieved")
        self.assertIn("FIT-02-FLW", result["operator_response"]["bottom_line"])
        self.assertTrue(any("No applicable approved SOP passage" in item
                            for item in result["operator_response"]["data_limitations"]))

        invented = answer_incident_question(
            event,
            "What changed in the historical flow readings?",
            context=context,
            llm_complete=lambda _prompt: json.dumps({
                "answer": "FIT-02-FLW reached 999 L/min before the alarm."
            }),
        )
        self.assertFalse(invented["llm_used"])
        self.assertTrue(invented["fallback_used"])
        self.assertNotIn("999 L/min", invented["answer"])

    def test_recurrence_uses_supplied_records_only(self):
        empty = build_assistant_response(example_event(), "Has this happened on this valve today?", similar_incidents=[])
        self.assertEqual(empty["uncertainty_status"], "incomplete_or_empty_day_history")
        found = build_assistant_response(example_event(), "Has this happened on this valve today?", similar_incidents=[
            {"primary_tag": "PIT-02-PRS", "timestamp": "2026-10-16T08:00:00Z"}
        ])
        self.assertIn("2026-10-16T08:00:00Z", found["similar_incidents"][0]["timestamp"])
        self.assertIn("2026-10-16T08:00:00Z", [item.get("timestamp") for item in found["operator_response"]["evidence"]])
        self.assertEqual(found["uncertainty_status"], "recorded_similar_incidents")

    def test_gemini_streaming_yields_chunks(self):
        from unittest.mock import patch, MagicMock
        from llm_provider import stream_chat

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = [
            'data: {"candidates": [{"content": {"parts": [{"text": "Part 1 "}]}}]}',
            'data: {"candidates": [{"content": {"parts": [{"text": "Part 2"}]}}]}',
        ]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "fake_test_key"}), \
             patch("requests.post", return_value=mock_resp):
            chunks = list(stream_chat("Test prompt"))
            self.assertEqual(chunks, ["Part 1 ", "Part 2"])


if __name__ == "__main__":
    unittest.main()
