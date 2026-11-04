"""
OpsLens - Unit Tests for Guidance Generation Engine (Component 8)
"""

import unittest
import uuid
import sys
import tempfile
import shutil
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import EventStory, EventStoryStep, Evidence, SupportingDelta, SopMatch, Guidance
from database import Database
from prompt_template import build_guidance_prompt, build_facts_payload, SYSTEM_INSTRUCTION
from fallback_template import generate_fallback_guidance
from guidance_generator import GuidanceGenerator


class TestGuidanceEngineUnit(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_guidance_unit.db"
        self.db = Database(db_path=self.db_path)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_prompt_template_serialization(self):
        """Verify prompt contains strict system instructions, facts JSON, and exact values."""
        event_id = str(uuid.uuid4())
        story = EventStory(
            event_id=event_id,
            steps=[],
            causal_label="Discharge Valve Restriction"
        )
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="VLV-04-POS",
            confidence_score=0.88,
            confidence_label="HIGH",
            supporting_deltas=[
                SupportingDelta(tag="VLV-04-POS", delta_pct=-44.9, direction="down")
            ]
        )
        sop = SopMatch(
            event_id=event_id,
            sop_id="SOP-P02-VLV-01",
            sop_title="Valve Restriction SOP",
            match_score=0.85,
            steps=["1. Check limit switches.", "2. Open bypass."],
            source="embedding"
        )

        prompt = build_guidance_prompt(story, evidence, sop)
        self.assertIn(SYSTEM_INSTRUCTION, prompt)
        self.assertIn("VLV-04-POS", prompt)
        self.assertIn("-44.9", prompt)
        self.assertIn("SOP-P02-VLV-01", prompt)
        self.assertIn("Discharge Valve Restriction", prompt)

    def test_deterministic_fallback_fidelity(self):
        """Verify fallback template never alters or invents numbers or tags."""
        event_id = str(uuid.uuid4())
        story = EventStory(event_id=event_id, steps=[], causal_label="Compressor High Vibration")
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="CMP-01-VIB",
            confidence_score=0.92,
            confidence_label="HIGH",
            supporting_deltas=[
                SupportingDelta(tag="CMP-01-VIB", delta_pct=65.4, direction="up")
            ]
        )
        sop = SopMatch(
            event_id=event_id,
            sop_id="SOP-C01-BRG-01",
            sop_title="Bearing Mitigation SOP",
            match_score=0.90,
            steps=[
                "1. Verify lube oil supply pressure.",
                "2. Check vibration probe connections.",
                "3. Trip compressor if vibration exceeds limit."
            ],
            source="embedding"
        )

        guidance = generate_fallback_guidance(story, evidence, sop)
        self.assertEqual(guidance.event_id, event_id)
        self.assertIn("CMP-01-VIB", guidance.explanation_text)
        self.assertIn("+65.4%", guidance.explanation_text)
        self.assertIn("HIGH", guidance.explanation_text)
        self.assertEqual(len(guidance.next_best_actions), 3)
        self.assertEqual(guidance.cited_sop_id, "SOP-C01-BRG-01")

    def test_guidance_generator_with_mock_llm(self):
        """Verify guidance generator parses valid LLM response and stores in SQLite."""
        event_id = str(uuid.uuid4())
        story = EventStory(event_id=event_id, steps=[], causal_label="Valve Throttling")
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="VLV-04-POS",
            confidence_score=0.82,
            confidence_label="HIGH",
            supporting_deltas=[
                SupportingDelta(tag="VLV-04-POS", delta_pct=-44.9, direction="down")
            ]
        )
        sop = SopMatch(
            event_id=event_id,
            sop_id="SOP-P02-VLV-01",
            sop_title="Valve SOP",
            match_score=0.85,
            steps=["1. Step one", "2. Step two", "3. Step three"],
            source="embedding"
        )

        def mock_caller(prompt: str) -> str:
            return (
                '```json\n'
                '{\n'
                f'  "event_id": "{event_id}",\n'
                '  "explanation_text": "Severe throttling on VLV-04-POS (-44.9%) led to discharge pressure excursion. Recovery advised.",\n'
                '  "next_best_actions": ["Action 1", "Action 2", "Action 3"],\n'
                '  "cited_sop_id": "SOP-P02-VLV-01"\n'
                '}\n'
                '```'
            )

        gen = GuidanceGenerator(db=self.db, api_caller=mock_caller)
        res = gen.generate(story, evidence, sop)

        self.assertEqual(res.event_id, event_id)
        self.assertIn("-44.9%", res.explanation_text)
        self.assertEqual(len(res.next_best_actions), 3)
        self.assertEqual(res.cited_sop_id, "SOP-P02-VLV-01")

        # Database verification
        records = self.db.get_guidance(event_id=event_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].explanation_text, res.explanation_text)

    def test_timeout_fallback_resilience(self):
        """Verify mock timeout triggers deterministic fallback cleanly."""
        event_id = str(uuid.uuid4())
        story = EventStory(event_id=event_id, steps=[], causal_label="Sensor Drift")
        evidence = Evidence(
            event_id=event_id,
            likely_contributor_tag="SEN-01",
            confidence_score=0.50,
            confidence_label="MEDIUM",
            supporting_deltas=[]
        )
        sop = SopMatch(
            event_id=event_id,
            sop_id="SOP-GEN-SEN-01",
            sop_title="Sensor SOP",
            match_score=0.70,
            steps=["1. Calibrate", "2. Verify", "3. Reset"],
            source="bm25"
        )

        def slow_caller(prompt: str) -> str:
            raise requests.exceptions.Timeout("Read timeout after 3.0s")

        gen = GuidanceGenerator(db=self.db, timeout=3.0, api_caller=slow_caller)
        res = gen.generate(story, evidence, sop)

        self.assertIsNotNone(res)
        self.assertEqual(res.event_id, event_id)
        self.assertEqual(res.cited_sop_id, "SOP-GEN-SEN-01")
        self.assertEqual(len(res.next_best_actions), 3)


if __name__ == "__main__":
    unittest.main()
