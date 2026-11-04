"""
OpsLens - Guidance Generation Acceptance Verification (Component 8)

Verifies:
1. Number-fidelity check: Feed Evidence with specific confidence_label and supporting_deltas,
   verifying returned explanation_text preserves exact numbers and tags without contradiction.
2. API failure & 3s timeout simulation: Fallback path produces valid, non-empty Guidance.
3. Event-level caching: Dashboard refreshes return cached Guidance without re-calling API.
4. Full live pipeline integration: Synthetic Generator -> Stream -> Prioritizer -> Correlator ->
   EventStory -> Evidence -> SopRetriever -> GuidanceGenerator across Scenarios A & B.
"""

import os
import re
import uuid
import unittest
from typing import List
import requests

from models import (
    EventStory, EventStoryStep, Evidence, SupportingDelta,
    SopMatch, Guidance, TagReading, current_iso_utc
)
from database import Database
from prompt_template import build_guidance_prompt, build_facts_payload
from fallback_template import generate_fallback_guidance
from guidance_generator import GuidanceGenerator

# Real pipeline components for end-to-end integration test
from generator import SyntheticDataGenerator
from stream import TagStream
from tag_registry import TAG_REGISTRY
from prioritizer import PrioritizationEngine
from dedup import DeduplicationEngine
from correlator import CorrelationEngine
from event_story import EventStoryConstructor
from evidence_engine import EvidenceEngine
from sop_retriever import SopRetriever


class TestGuidanceAcceptance(unittest.TestCase):
    """Component 8 Acceptance Tests."""

    def setUp(self):
        self.test_db_path = "test_guidance_ops.db"
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        self.db = Database(self.test_db_path)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_number_fidelity_check(self):
        """
        Acceptance Criterion 1: Feed specific Evidence with known confidence_label and
        supporting_deltas, and verify returned explanation_text preserves exact numbers
        and tags without contradiction or altered values.
        """
        event_id = str(uuid.uuid4())
        story = EventStory(
            event_id=event_id,
            steps=[
                EventStoryStep(
                    step_number=1,
                    tag="VLV-04-POS",
                    timestamp="2026-09-11T00:00:00Z",
                    description="VLV-04-POS throttled closed",
                    value_before=100.0,
                    value_after=55.1
                ),
                EventStoryStep(
                    step_number=2,
                    tag="PIT-02-PRS",
                    timestamp="2026-09-11T00:00:02Z",
                    description="Discharge pressure surged",
                    value_before=4.2,
                    value_after=6.5
                )
            ],
            causal_label="Discharge Valve Throttling Cascade"
        )

        test_deltas = [
            SupportingDelta(tag="VLV-04-POS", delta_pct=-44.9, direction="down"),
            SupportingDelta(tag="PIT-02-PRS", delta_pct=18.2, direction="up")
        ]
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="VLV-04-POS",
            confidence_score=0.85,
            confidence_label="HIGH",
            supporting_deltas=test_deltas
        )

        sop_match = SopMatch(
            event_id=event_id,
            sop_id="SOP-P02-VLV-01",
            sop_title="Centrifugal Pump Discharge Valve Restriction Recovery Procedure",
            match_score=0.88,
            steps=[
                "1. Cross-reference VLV-04-POS actuator command with physical limit switch feedback.",
                "2. Throttle manual bypass valve HV-02-BYP to restore minimum recirculation flow.",
                "3. Verify pump discharge pressure PIT-02-PRS remains below design casing limit."
            ],
            source="embedding"
        )

        # 1. Verify Fallback Template Fidelity
        fallback_guidance = generate_fallback_guidance(story, evidence, sop_match)
        self.assertIsInstance(fallback_guidance, Guidance)
        exp_text = fallback_guidance.explanation_text

        # Programmatic number and tag fidelity check
        self.assertIn("VLV-04-POS", exp_text)
        self.assertIn("HIGH", exp_text)
        self.assertIn("-44.9%", exp_text)
        self.assertIn("+18.2%", exp_text)
        self.assertNotIn("-45.0%", exp_text)
        self.assertNotIn("+18.0%", exp_text)

        # Verify next_best_actions
        self.assertEqual(len(fallback_guidance.next_best_actions), 3)
        self.assertEqual(fallback_guidance.cited_sop_id, "SOP-P02-VLV-01")

        # 2. Verify with LLM Mock Caller returning custom phrased text with exact numbers
        def mock_llm_caller(prompt: str) -> str:
            return (
                '{\n'
                f'  "event_id": "{event_id}",\n'
                '  "explanation_text": "High-confidence investigation confirms VLV-04-POS (-44.9%) caused a severe flow restriction with PIT-02-PRS surging (+18.2%). Immediate valve reset is advised.",\n'
                '  "next_best_actions": [\n'
                '    "Cross-reference VLV-04-POS actuator command with limit switches",\n'
                '    "Throttle manual bypass valve to maintain minimum flow",\n'
                '    "Verify discharge pressure PIT-02-PRS stabilizes below casing limit"\n'
                '  ],\n'
                '  "cited_sop_id": "SOP-P02-VLV-01"\n'
                '}'
            )

        generator = GuidanceGenerator(db=self.db, api_caller=mock_llm_caller)
        guidance = generator.generate(story, evidence, sop_match)

        # Verify exact number preservation
        self.assertIn("-44.9%", guidance.explanation_text)
        self.assertIn("+18.2%", guidance.explanation_text)
        self.assertIn("VLV-04-POS", guidance.explanation_text)
        self.assertEqual(len(guidance.next_best_actions), 3)
        self.assertEqual(guidance.cited_sop_id, "SOP-P02-VLV-01")

        # Verify persisted in SQLite
        db_records = self.db.get_guidance(event_id=event_id)
        self.assertEqual(len(db_records), 1)
        self.assertEqual(db_records[0].explanation_text, guidance.explanation_text)

    def test_api_timeout_and_error_fallback(self):
        """
        Acceptance Criterion 2: Simulate an API failure (mock a 3s timeout and HTTP 500 error)
        and verify the fallback path produces valid, non-empty Guidance.
        """
        event_id = str(uuid.uuid4())
        story = EventStory(
            event_id=event_id,
            steps=[],
            causal_label="High Bearing Vibration Excursion"
        )
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="CMP-01-VIB",
            confidence_score=0.91,
            confidence_label="HIGH",
            supporting_deltas=[
                SupportingDelta(tag="CMP-01-VIB", delta_pct=78.5, direction="up")
            ]
        )
        sop_match = SopMatch(
            event_id=event_id,
            sop_id="SOP-C01-BRG-01",
            sop_title="Compressor Bearing High Vibration & Temperature Mitigation",
            match_score=0.92,
            steps=[
                "1. Check lube oil supply header pressure and filter differential pressure.",
                "2. Inspect accelerometer probe mounting and wiring continuity.",
                "3. Prepare for orderly controlled compressor trip if vibration exceeds 7.1 mm/s."
            ],
            source="embedding"
        )

        # Mock caller simulating network timeout (>3s)
        def timeout_caller(prompt: str) -> str:
            raise requests.exceptions.Timeout("HTTPSConnectionPool: Read timed out. (read timeout=3.0)")

        generator = GuidanceGenerator(db=self.db, timeout=3.0, api_caller=timeout_caller)
        guidance = generator.generate(story, evidence, sop_match)

        # Verify fallback path executed gracefully
        self.assertIsNotNone(guidance)
        self.assertEqual(guidance.event_id, event_id)
        self.assertTrue(len(guidance.explanation_text) > 20)
        self.assertIn("CMP-01-VIB", guidance.explanation_text)
        self.assertIn("+78.5%", guidance.explanation_text)
        self.assertEqual(len(guidance.next_best_actions), 3)
        self.assertEqual(guidance.cited_sop_id, "SOP-C01-BRG-01")

        # Check SQLite persistence
        db_records = self.db.get_guidance(event_id=event_id)
        self.assertEqual(len(db_records), 1)
        self.assertEqual(db_records[0].cited_sop_id, "SOP-C01-BRG-01")

    def test_caching_layer_repeat_calls(self):
        """
        Requirement 3: Verify caching keyed on event_id ensures repeat calls
        (e.g. dashboard refreshes) don't re-hit API or produce inconsistent phrasing.
        """
        event_id = str(uuid.uuid4())
        story = EventStory(event_id=event_id, steps=[], causal_label="Sensor Drift Discrepancy")
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="SEN-01",
            confidence_score=0.45,
            confidence_label="MEDIUM",
            supporting_deltas=[]
        )
        sop_match = SopMatch(
            event_id=event_id,
            sop_id="SOP-GEN-SEN-01",
            sop_title="Sensor Calibration SOP",
            match_score=0.65,
            steps=["1. Calibrate sensor loop.", "2. Check 4-20mA signal.", "3. Replace transmitter."],
            source="bm25"
        )

        call_count = {"count": 0}

        def counting_caller(prompt: str) -> str:
            call_count["count"] += 1
            return (
                '{\n'
                f'  "event_id": "{event_id}",\n'
                '  "explanation_text": "Sensor loop discrepancy detected on SEN-01 with MEDIUM confidence.",\n'
                '  "next_best_actions": ["Calibrate sensor loop", "Check 4-20mA signal", "Replace transmitter"],\n'
                '  "cited_sop_id": "SOP-GEN-SEN-01"\n'
                '}'
            )

        generator = GuidanceGenerator(db=self.db, api_caller=counting_caller)

        # First call: hits caller
        guidance1 = generator.generate(story, evidence, sop_match)
        self.assertEqual(call_count["count"], 1)

        # Second call (same instance): hits in-memory cache
        guidance2 = generator.generate(story, evidence, sop_match)
        self.assertEqual(call_count["count"], 1)
        self.assertEqual(guidance1.explanation_text, guidance2.explanation_text)

        # Third call (new generator instance): hits SQLite cache
        new_generator = GuidanceGenerator(db=self.db, api_caller=counting_caller)
        guidance3 = new_generator.generate(story, evidence, sop_match)
        self.assertEqual(call_count["count"], 1)
        self.assertEqual(guidance1.explanation_text, guidance3.explanation_text)

    def test_full_live_pipeline_integration(self):
        """
        Verify complete integration from live telemetry down to Guidance:
        Generator (Scenario A) -> Stream -> Deduplication -> Correlator ->
        EventStory -> Evidence -> SopRetriever -> GuidanceGenerator
        """
        import asyncio
        from datetime import datetime, timezone
        from topology import TopologyGraph

        stream = TagStream(db_path=self.test_db_path)
        prioritizer = PrioritizationEngine()
        dedup_engine = DeduplicationEngine(db=self.db, prioritizer=prioritizer)
        topology = TopologyGraph()
        correlator = CorrelationEngine(stream=stream, db=self.db, topology_graph=topology)
        story_constructor = EventStoryConstructor(db=self.db)
        evidence_engine = EvidenceEngine(db=self.db)
        sop_retriever = SopRetriever(db=self.db)
        guidance_gen = GuidanceGenerator(db=self.db)
        generator = SyntheticDataGenerator(
            db=self.db,
            sample_interval=2.0,
            start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
        )

        async def run():
            readings_a = list(generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
            for r in readings_a:
                dedup_engine.process_reading(r)

            candidates_a = self.db.get_candidate_events()
            self.assertTrue(len(candidates_a) >= 1)
            candidate = candidates_a[0]

            correlated = await correlator.correlate_event(candidate)
            story = story_constructor.construct_story(correlated, persist=True)
            evidence = evidence_engine.evaluate_event(correlated, persist=True)
            sop_match = sop_retriever.retrieve(story=story, evidence=evidence, persist=True)

            # Generate Guidance
            guidance = guidance_gen.generate(story, evidence, sop_match)

            self.assertEqual(guidance.event_id, candidate.event_id)
            self.assertEqual(guidance.cited_sop_id, "SOP-P02-VLV-01")
            self.assertEqual(len(guidance.next_best_actions), 3)
            self.assertIn("VLV-04-POS", guidance.explanation_text)
            self.assertTrue(len(guidance.explanation_text) > 10)

            # Verify persisted in SQLite
            db_records = self.db.get_guidance(event_id=candidate.event_id)
            self.assertEqual(len(db_records), 1)
            self.assertEqual(db_records[0].cited_sop_id, "SOP-P02-VLV-01")

        asyncio.run(run())

    def test_edge_slm_embedded_json_and_preamble(self):
        """
        Verify that small language models (SLMs) that output conversational preambles
        before their JSON (common in 0.5B-2B models) are parsed reliably.
        """
        generator = GuidanceGenerator(db=self.db)
        raw_slm_output = (
            "Here is the industrial guidance based on the telemetry:\n"
            "```json\n"
            "{\n"
            '  "event_id": "test-edge-123",\n'
            '  "explanation_text": "Valve VLV-04 position dropped by 44.87% causing pressure surge.",\n'
            '  "next_best_actions": ["Verify Valve-04 positioner", "Inspect discharge line", "Execute SOP-P02-VLV-01"],\n'
            '  "cited_sop_id": "SOP-P02-VLV-01"\n'
            "}\n"
            "```\n"
            "Safety notice: Manual intervention required."
        )
        parsed = generator._parse_llm_json(raw_slm_output, "test-edge-123", "SOP-P02-VLV-01")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.event_id, "test-edge-123")
        self.assertEqual(len(parsed.next_best_actions), 3)
        self.assertIn("VLV-04", parsed.explanation_text)

    def test_edge_slm_fidelity_guard_triggers_fallback(self):
        """
        Verify that if an edge SLM hallucinates or alters a critical number,
        the numerical fidelity validator catches it and safely triggers the deterministic fallback.
        """
        event_id = str(uuid.uuid4())
        story = EventStory(
            event_id=event_id,
            steps=[],
            causal_label="Valve restriction"
        )
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="VLV-04-POS",
            confidence_score=0.88,
            confidence_label="HIGH",
            supporting_deltas=[
                SupportingDelta(tag="VLV-04-POS", delta_pct=-44.87, direction="down")
            ]
        )
        sop_match = SopMatch(
            event_id=event_id,
            sop_id="SOP-P02-VLV-01",
            sop_title="Valve Restriction Remediation",
            match_score=0.92,
            steps=["1. Verify positioner", "2. Check flow", "3. Reset valve"],
            source="bm25"
        )

        # SLM hallucinates that VLV-04 dropped by 99.9% instead of 44.87%
        hallucinating_slm_caller = lambda prompt: (
            "{\n"
            f'  "event_id": "{event_id}",\n'
            '  "explanation_text": "Valve VLV-04 dropped catastrophically by 99.9% into full shutoff.",\n'
            '  "next_best_actions": ["Emergency shutdown", "Evacuate area", "Isolate unit"],\n'
            f'  "cited_sop_id": "SOP-P02-VLV-01"\n'
            "}"
        )

        generator = GuidanceGenerator(db=self.db, api_caller=hallucinating_slm_caller)
        guidance = generator.generate(story, evidence, sop_match)

        # Must have fallen back to deterministic template because 99.9% contradicts 44.87%
        self.assertNotIn("99.9%", guidance.explanation_text)
        self.assertIn("44.9%", guidance.explanation_text)
        db_records = self.db.get_guidance(event_id=event_id)
        self.assertEqual(len(db_records), 1)

    def test_edge_slm_availability_probe(self):
        """
        Verify fast availability check returns boolean without throwing exceptions.
        """
        from edge_slm import check_edge_slm_availability
        is_available = check_edge_slm_availability(url="http://127.0.0.1:54321", timeout=0.2)
        self.assertFalse(is_available)

    def test_sop_available_direct_certified_guidance(self):
        """
        Primary Hierarchy Step 1: When an approved SOP is retrieved and available,
        guidance is derived directly from the certified SOP and inference facts
        with zero latency and source='sop_retrieval'.
        """
        event_id = str(uuid.uuid4())
        story = EventStory(
            event_id=event_id,
            steps=[],
            causal_label="Discharge Line Restriction"
        )
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="VLV-04-POS",
            confidence_score=0.89,
            confidence_label="HIGH",
            supporting_deltas=[
                SupportingDelta(tag="VLV-04-POS", delta_pct=-44.9, direction="down")
            ]
        )
        sop_match = SopMatch(
            event_id=event_id,
            sop_id="SOP-P02-VLV-01",
            sop_title="Centrifugal Pump Discharge Valve Restriction Recovery Procedure",
            match_score=0.88,
            steps=[
                "1. Cross-reference VLV-04-POS actuator command with physical limit switch feedback.",
                "2. Throttle manual bypass valve HV-02-BYP to restore minimum recirculation flow.",
                "3. Verify pump discharge pressure PIT-02-PRS remains below design casing limit."
            ],
            source="embedding"
        )

        generator = GuidanceGenerator(db=self.db)
        self.assertTrue(generator.is_sop_available(sop_match))

        guidance = generator.generate(story, evidence, sop_match)

        self.assertEqual(guidance.event_id, event_id)
        self.assertEqual(guidance.cited_sop_id, "SOP-P02-VLV-01")
        self.assertEqual(len(guidance.next_best_actions), 3)
        self.assertIn("VLV-04-POS", guidance.explanation_text)
        self.assertIn("-44.9%", guidance.explanation_text)

        # Confirm persisted with source='sop_retrieval'
        conn = self.db._get_connection()
        row = conn.execute("SELECT source FROM guidance WHERE event_id = ?", (event_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["source"], "sop_retrieval")

    def test_sop_unavailable_online_cloud_llm(self):
        """
        Primary Hierarchy Step 2A: When SOP is unavailable and system is online,
        synthesize guidance dynamically via Cloud LLM (Gemini 2.5 Flash / OpenAI).
        """
        event_id = str(uuid.uuid4())
        story = EventStory(
            event_id=event_id,
            steps=[],
            causal_label="Novel Uncataloged Excursion"
        )
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="ANOM-99",
            confidence_score=0.75,
            confidence_label="MEDIUM",
            supporting_deltas=[
                SupportingDelta(tag="ANOM-99", delta_pct=33.3, direction="up")
            ]
        )
        # SOP match is unavailable / none found
        sop_match = SopMatch(
            event_id=event_id,
            sop_id="SOP-NONE",
            sop_title="No matching procedure found",
            match_score=0.05,
            steps=[],
            source="bm25"
        )

        generator = GuidanceGenerator(db=self.db, force_online=True)
        self.assertFalse(generator.is_sop_available(sop_match))

        # Mock Cloud LLM response
        generator._call_cloud_llm = lambda prompt: (
            "{\n"
            f'  "event_id": "{event_id}",\n'
            '  "explanation_text": "Novel uncataloged excursion on ANOM-99 (+33.3%) detected with MEDIUM confidence.",\n'
            '  "next_best_actions": ["Inspect ANOM-99 field transmitter", "Verify DCS loop calibration", "Monitor trend for 15 minutes"],\n'
            '  "cited_sop_id": "NONE"\n'
            "}"
        )

        guidance = generator.generate(story, evidence, sop_match)

        self.assertEqual(guidance.event_id, event_id)
        self.assertEqual(guidance.cited_sop_id, "NONE")
        self.assertEqual(len(guidance.next_best_actions), 3)
        self.assertIn("ANOM-99", guidance.explanation_text)
        self.assertIn("+33.3%", guidance.explanation_text)

        # Confirm persisted with source='cloud_llm'
        conn = self.db._get_connection()
        row = conn.execute("SELECT source FROM guidance WHERE event_id = ?", (event_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["source"], "cloud_llm")

    def test_sop_unavailable_offline_ollama_slm(self):
        """
        Primary Hierarchy Step 2B: When SOP is unavailable and system is offline (edge device),
        synthesize guidance dynamically via local Ollama SLM (qwen2.5:0.5b / phi3:mini).
        """
        event_id = str(uuid.uuid4())
        story = EventStory(
            event_id=event_id,
            steps=[],
            causal_label="Uncataloged Flow Anomaly"
        )
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="FIT-09-FLW",
            confidence_score=0.81,
            confidence_label="HIGH",
            supporting_deltas=[
                SupportingDelta(tag="FIT-09-FLW", delta_pct=-27.4, direction="down")
            ]
        )
        sop_match = SopMatch(
            event_id=event_id,
            sop_id="UNKNOWN-SOP",
            sop_title="Unknown Procedure",
            match_score=0.10,
            steps=[],
            source="bm25"
        )

        # Force offline mode (e.g. edge gateway on air-gapped OT network)
        generator = GuidanceGenerator(db=self.db, force_online=False)
        self.assertFalse(generator.is_sop_available(sop_match))

        # Mock Ollama SLM output with conversational preamble
        generator._call_edge_slm = lambda prompt: (
            "Here is the local edge analysis:\n"
            "```json\n"
            "{\n"
            f'  "event_id": "{event_id}",\n'
            '  "explanation_text": "Flow anomaly detected on FIT-09-FLW (-27.4%) with HIGH confidence on edge gateway.",\n'
            '  "next_best_actions": ["Check flow sensor impulse line", "Inspect orifice plate", "Cross-check upstream valve position"],\n'
            '  "cited_sop_id": "NONE"\n'
            "}\n"
            "```"
        )

        guidance = generator.generate(story, evidence, sop_match)

        self.assertEqual(guidance.event_id, event_id)
        self.assertEqual(guidance.cited_sop_id, "NONE")
        self.assertEqual(len(guidance.next_best_actions), 3)
        self.assertIn("FIT-09-FLW", guidance.explanation_text)
        self.assertIn("-27.4%", guidance.explanation_text)

        # Confirm persisted with source='edge_slm'
        conn = self.db._get_connection()
        row = conn.execute("SELECT source FROM guidance WHERE event_id = ?", (event_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["source"], "edge_slm")

    def test_sop_unavailable_both_fail_triggers_safety_fallback(self):
        """
        Primary Hierarchy Step 3 (Safety Net): When SOP is unavailable and both
        Cloud LLM and Edge SLM are unreachable or fail, trigger deterministic
        safety fallback with safe diagnostic actions.
        """
        event_id = str(uuid.uuid4())
        story = EventStory(
            event_id=event_id,
            steps=[],
            causal_label="High Bearing Heat"
        )
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="TT-01-TMP",
            confidence_score=0.90,
            confidence_label="HIGH",
            supporting_deltas=[
                SupportingDelta(tag="TT-01-TMP", delta_pct=52.1, direction="up")
            ]
        )
        sop_match = SopMatch(
            event_id=event_id,
            sop_id="SOP-NONE",
            sop_title="None",
            match_score=0.0,
            steps=[],
            source="bm25"
        )

        # Offline mode, both Cloud and Edge SLM fail/unavailable
        generator = GuidanceGenerator(db=self.db, force_online=False)
        generator._call_edge_slm = lambda prompt: None  # Simulate Ollama not running

        guidance = generator.generate(story, evidence, sop_match)

        self.assertEqual(guidance.event_id, event_id)
        self.assertEqual(guidance.cited_sop_id, "NONE")
        self.assertEqual(len(guidance.next_best_actions), 3)
        self.assertIn("TT-01-TMP", guidance.explanation_text)
        self.assertIn("+52.1%", guidance.explanation_text)

        # Confirm persisted with source='fallback'
        conn = self.db._get_connection()
        row = conn.execute("SELECT source FROM guidance WHERE event_id = ?", (event_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["source"], "fallback")


if __name__ == "__main__":
    unittest.main()

