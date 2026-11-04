"""Qwen/Ollama diagnosis: prompt scope, streaming, validation, fallback,
caching and health — over real HTTP against a fake Ollama /api/chat server."""
import asyncio
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import httpx

import ai_diagnosis
import incident_catalog as catalog
from alarm_lifecycle import get_lifecycle_manager
from database import Database
from generator import SyntheticDataGenerator
from tag_registry import TAG_REGISTRY

GOOD = """## 1. Incident summary
- CONFIRMED: ALM-WW-101-HH wet well high-high on LiftStation-01; LIT-101-WWL reads 3.85 m.
## 2. Confirmed observations
- CONFIRMED: FIT-102-FLW 90 m³/h, PIT-102-DIS 1.1 bar, MOT-102-CUR 19 A. P101-FAULT active; MOT-101-CUR 0 A.
## 3. Possible root causes
- HYPOTHESIS: P-102 is partly clogged (low flow, low pressure, low current) while P-101 tripped on winding temperature.
## 4. Evidence for and against
- For: FIT-102-FLW fell before P101-FAULT. Against: no local inspection result is recorded.
## 5. Missing information
- UNKNOWN: impeller condition and the P-101 fault code.
## 6. Recommended safe operator checks
- SOP-LFT-001 step 4: check pump status, motor temperature and local level (DRAFT, NOT APPROVED).
## 7. Final engineering assessment
- Loss of pumping capacity on both pumps is consistent with the rising level; confirm in the field.
"""


class _FakeOllamaChat(BaseHTTPRequestHandler):
    reply = GOOD
    delay = 0.0
    status = 200
    received = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"models": [{"name": "qwen2.5:3b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        cls = type(self)
        cls.received.append((self.path, payload))
        if cls.status != 200:
            self.send_response(cls.status)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        time.sleep(cls.delay)
        words = cls.reply.split(" ")
        try:
            for i, w in enumerate(words):
                tok = w + (" " if i < len(words) - 1 else "")
                self.wfile.write((json.dumps({"message": {"role": "assistant", "content": tok}, "done": False}) + "\n").encode())
                self.wfile.flush()
            self.wfile.write((json.dumps({"message": {"role": "assistant", "content": ""}, "done": True,
                                          "total_duration": 2_000_000_000, "load_duration": 10_000_000,
                                          "prompt_eval_count": 1200, "eval_count": len(words),
                                          "eval_duration": 1_000_000_000}) + "\n").encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _build_event(scenario_id, db, orch, start):
    before = {c.event_id for c in db.get_candidate_events()}
    gen = SyntheticDataGenerator(db=db, sample_interval=2.0, start_time=start)
    async for r in gen.run_scenario_async(scenario_id, speed_multiplier=float("inf")):
        await orch.process_reading(r)
    while orch._in_flight_tasks:
        await asyncio.gather(*list(orch._in_flight_tasks.values()), return_exceptions=True)
    for c in db.get_candidate_events():
        if c.event_id not in before:
            await orch.process_candidate_event(c)
    while orch._in_flight_tasks:
        await asyncio.gather(*list(orch._in_flight_tasks.values()), return_exceptions=True)
    new = [c for c in db.get_candidate_events() if c.event_id not in before]
    return orch.get_full_event(new[0].event_id)


class DiagnosisTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllamaChat)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    async def asyncSetUp(self):
        get_lifecycle_manager().clear_all()
        ai_diagnosis.CACHE.clear()
        _FakeOllamaChat.reply, _FakeOllamaChat.delay, _FakeOllamaChat.status = GOOD, 0.0, 200
        _FakeOllamaChat.received = []
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "ollama", "EDGE_LLM_URL": self.url,
                                           "EDGE_LLM_MODEL": "qwen2.5:3b", "OPSLENS_OLLAMA_TIMEOUT": "5"})
        self.env.start()
        import llm_provider
        llm_provider._verified_provider = None
        from orchestrator import OpsLensOrchestrator
        self.db = Database(db_path=Path(self.tmp.name) / "d.db")
        with patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "none"}):
            self.orch = OpsLensOrchestrator(db=self.db)
            self.event = await _build_event("wet_well_high_level", self.db, self.orch,
                                            datetime.now(timezone.utc) - timedelta(minutes=6))

    async def asyncTearDown(self):
        self.env.stop()
        await self.orch.stop()
        get_lifecycle_manager().clear_all()
        self.tmp.cleanup()

    # -- prompt scope ------------------------------------------------------
    def test_facts_hold_only_this_incident_and_its_draft_sop(self):
        facts = ai_diagnosis.build_facts(self.event, self.db)
        spec = catalog.SCENARIO_BY_ID["wet_well_high_level"]
        self.assertEqual(set(facts["incident_tags"]), set(catalog.scenario_tags(spec)))
        self.assertTrue({r["tag"] for r in facts["readings"]} <= set(facts["incident_tags"]))
        self.assertTrue({s["tag"] for s in facts["sequence"]} <= set(facts["incident_tags"]))
        self.assertEqual(facts["sop"]["sop_id"], "SOP-LFT-001")
        self.assertFalse(facts["sop"]["approved"])
        self.assertIn("NOT APPROVED", facts["sop"]["status"])
        self.assertEqual(facts["data_source"], "SIMULATED")
        values = {r["tag"]: r["value"] for r in facts["readings"]}
        self.assertEqual(values["LIT-101-WWL"], 3.85)
        self.assertEqual(values["FIT-102-FLW"], 90)
        prompt = ai_diagnosis.build_prompt(facts)
        # The simulator's scripted cause is not handed to the model.
        for cause in spec.root.values():
            self.assertNotIn(cause, prompt)
        self.assertNotIn("Pump-02", prompt)
        self.assertLess(len(prompt) + len(ai_diagnosis.SYSTEM_PROMPT), 9000)
        stamps = [s["time"] for s in facts["sequence"]]
        self.assertEqual(stamps, sorted(stamps))

    # -- real streaming call ----------------------------------------------
    def test_ollama_stream_is_used_validated_cached_and_reported(self):
        items = list(ai_diagnosis.stream_diagnosis(self.event, self.db))
        self.assertEqual(items[0]["type"], "meta")
        self.assertGreater(sum(1 for i in items if i["type"] == "token"), 20)
        done = items[-1]
        self.assertEqual(done["engine"], "ollama", done.get("fallback_reason"))
        self.assertTrue(done["validation"]["valid"], done["validation"])
        self.assertEqual(done["validation"]["cited_sop_steps"], [4])
        self.assertIsNotNone(done["latency"]["time_to_first_token_ms"])
        self.assertEqual(done["latency"]["prompt_tokens"], 1200)
        path, payload = _FakeOllamaChat.received[-1]
        self.assertEqual(path, "/api/chat")
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["model"], "qwen2.5:3b")
        self.assertIn("keep_alive", payload)
        self.assertEqual(payload["options"]["num_ctx"], 4096)
        self.assertIn("NOT APPROVED", payload["messages"][1]["content"])
        from llm_provider import provider_status
        self.assertTrue(provider_status()["verified"])
        self.assertTrue(ai_diagnosis.LAST_CALL["succeeded"])
        # Second request: cache, no new model call.
        calls = len(_FakeOllamaChat.received)
        again = ai_diagnosis.diagnose(self.event, self.db)
        self.assertTrue(again["cached"])
        self.assertEqual(len(_FakeOllamaChat.received), calls)

    # -- validation -------------------------------------------------------
    def test_foreign_incident_tag_is_rejected(self):
        _FakeOllamaChat.reply = GOOD.replace("MOT-101-CUR 0 A", "PIT-02-PRS 9 bar on Pump-02")
        done = ai_diagnosis.diagnose(self.event, self.db)
        self.assertEqual(done["engine"], "deterministic_fallback")
        self.assertIn("PIT-02-PRS", done["fallback_reason"])
        self.assertEqual(done["label"], ai_diagnosis.FALLBACK_LABEL)
        self.assertIn("PIT-02-PRS", done["rejected_ai_text"])
        self.assertNotIn("PIT-02-PRS", done["text"])

    def test_invented_readings_and_steps_are_rejected(self):
        _FakeOllamaChat.reply = GOOD.replace("3.85 m", "4.72 m").replace("90 m³/h", "77 m³/h").replace(
            "1.1 bar", "1.37 bar").replace("step 4", "step 14")
        done = ai_diagnosis.diagnose(self.event, self.db)
        self.assertEqual(done["engine"], "deterministic_fallback")
        self.assertIn("numbers not found", done["fallback_reason"])
        self.assertIn("SOP steps that do not exist", done["fallback_reason"])

    def test_control_claims_and_approved_sop_are_rejected(self):
        check = ai_diagnosis.validate(GOOD + "\nI have reset the pump.", ai_diagnosis.build_facts(self.event, self.db))
        self.assertFalse(check["valid"])
        check = ai_diagnosis.validate(GOOD.replace("(DRAFT, NOT APPROVED)", "per the approved SOP"),
                                      ai_diagnosis.build_facts(self.event, self.db))
        self.assertFalse(check["valid"])
        check = ai_diagnosis.validate(GOOD.replace("## 4. Evidence for and against", "").replace(
            "## 5. Missing information", "").replace("## 7. Final engineering assessment", ""),
            ai_diagnosis.build_facts(self.event, self.db))
        self.assertIn("missing sections", " ".join(check["rejected_reasons"]))

    # -- fallback ---------------------------------------------------------
    def test_ollama_down_gives_labelled_fallback_and_is_not_cached(self):
        with patch.dict(os.environ, {"EDGE_LLM_URL": f"http://127.0.0.1:{_free_port()}"}):
            done = ai_diagnosis.diagnose(self.event, self.db)
        self.assertEqual(done["engine"], "deterministic_fallback")
        self.assertIn("not running", done["fallback_reason"])
        self.assertTrue(done["text"].startswith("> " + ai_diagnosis.FALLBACK_LABEL))
        for i, name in enumerate(ai_diagnosis.SECTIONS, 1):
            self.assertIn(f"## {i}. {name}", done["text"])
        self.assertFalse(ai_diagnosis.LAST_CALL["succeeded"])
        from llm_provider import provider_status
        self.assertFalse(provider_status()["verified"])
        # Ollama back: the next request really calls it (failure was not cached).
        self.assertEqual(ai_diagnosis.diagnose(self.event, self.db)["engine"], "ollama")

    def test_model_missing_and_provider_none(self):
        _FakeOllamaChat.status = 404
        done = ai_diagnosis.diagnose(self.event, self.db)
        self.assertIn("ollama pull", done["fallback_reason"])
        with patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "none"}):
            done = ai_diagnosis.diagnose(self.event, self.db)
        self.assertEqual(done["engine"], "deterministic_fallback")
        self.assertIn("No LLM provider", done["fallback_reason"])

    def test_fallback_text_passes_its_own_validator(self):
        facts = ai_diagnosis.build_facts(self.event, self.db)
        self.assertTrue(ai_diagnosis.validate(ai_diagnosis.deterministic_diagnosis(facts), facts)["valid"])

    # -- HTTP --------------------------------------------------------------
    async def test_sse_endpoint_streams_meta_tokens_done_and_health_reports_call(self):
        from api.routes import create_app
        app = create_app(orchestrator=self.orch)
        _FakeOllamaChat.delay = 0.2
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=20) as client:
            r = await client.get(f"/api/events/{self.event['event_id']}/diagnosis/stream")
            self.assertEqual(r.status_code, 200)
            kinds = [line.split(": ", 1)[1] for line in r.text.splitlines() if line.startswith("event: ")]
            self.assertEqual(kinds[0], "meta")
            self.assertIn("token", kinds)
            self.assertEqual(kinds[-1], "done")
            done = json.loads(r.text.strip().splitlines()[-1].split("data: ", 1)[1])
            self.assertEqual(done["engine"], "ollama")
            self.assertGreaterEqual(done["latency"]["time_to_first_token_ms"], 200)
            health = (await client.get("/api/copilot/ollama")).json()
            self.assertTrue(health["verified_in_this_process"])
            self.assertTrue(health["last_diagnosis_call"]["succeeded"])
            self.assertEqual((await client.get("/api/events/nope/diagnosis")).status_code, 404)


class SixIncidentFactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_incident_prompt_has_only_its_tags_and_sop(self):
        get_lifecycle_manager().clear_all()
        from orchestrator import OpsLensOrchestrator
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "none"}):
            db = Database(db_path=Path(tmp) / "s.db")
            orch = OpsLensOrchestrator(db=db)
            start = datetime.now(timezone.utc) - timedelta(hours=3)
            all_tags = {t for s in catalog.SCENARIOS for t in catalog.scenario_tags(s)}
            for i, spec in enumerate(catalog.SCENARIOS):
                event = await _build_event(spec.scenario_id, db, orch, start + timedelta(minutes=20 * i))
                facts = ai_diagnosis.build_facts(event, db)
                prompt = ai_diagnosis.build_prompt(facts)
                with self.subTest(scenario=spec.scenario_id):
                    own = set(catalog.scenario_tags(spec))
                    self.assertEqual(facts["sop"]["sop_id"], spec.sop_id)
                    self.assertEqual(facts["sop"]["coverage"], spec.sop_coverage)
                    self.assertEqual(facts["primary_alarm"]["tag"], spec.primary_alarm)
                    for other in all_tags - own:
                        self.assertNotIn(f'"{other}"', prompt)
                    self.assertTrue(ai_diagnosis.validate(ai_diagnosis.deterministic_diagnosis(facts), facts)["valid"])
            await orch.stop()
        get_lifecycle_manager().clear_all()


if __name__ == "__main__":
    unittest.main()
