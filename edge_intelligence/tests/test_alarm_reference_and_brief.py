"""Tests for the SOP-manual alarm reference, alarm lifecycle semantics,
data-source labelling, verbatim SOP steps and the deterministic operator brief.

These run without Ollama, Qdrant, Docker, sentence-transformers or a PLC.
"""
import asyncio
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

import alarm_config
from alarm_lifecycle import AlarmLifecycleManager, get_lifecycle_manager
from api.copilot_routes import alarm_state_rows, data_source_state
from database import Database
from dedup import DeduplicationEngine
from models import TagReading
from prioritizer import PrioritizationEngine
from tag_registry import TAG_REGISTRY


def _ts(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _reading(tag, value, when, source="simulated", quality="VALID", alarm_state=None):
    entry = TAG_REGISTRY[tag]
    return TagReading(tag=tag, value=value, timestamp=_ts(when), unit=entry.unit,
                      equipment_id=entry.equipment_id, data_source=source,
                      data_quality=quality, alarm_state=alarm_state)


class AlarmReferenceTests(unittest.TestCase):
    """The reference file must mirror SOP-MAN-000 exactly, with page numbers."""

    def test_every_definition_cites_a_page_of_the_29_page_manual(self):
        ref = alarm_config.load_reference()
        self.assertEqual(ref["source_document"]["document_id"], "SOP-MAN-000")
        self.assertIn("NOT APPROVED", ref["source_document"]["approval_status"])
        self.assertGreaterEqual(len(ref["definitions"]), 25)
        for item in ref["definitions"]:
            self.assertTrue(1 <= item["source_page"] <= 29, item["id"])
            for limit in item["limits"]:
                self.assertTrue(1 <= limit["source_page"] <= 29, item["id"])
            # Unspecified facts are labelled, never guessed.
            self.assertIn(item["reset_condition"], ("NOT SPECIFIED",))

    def test_wet_well_limits_match_pages_14_and_15(self):
        item = alarm_config.definition_for_tag("LIT-101-WWL")
        self.assertEqual(item["sop_id"], "SOP-LFT-001")
        limits = {l["name"]: (l["value"], l["source_page"]) for l in item["limits"]}
        self.assertEqual(limits["HIGH"], (3.2, 14))
        self.assertEqual(limits["HIGH-HIGH"], (3.6, 14))
        self.assertEqual(limits["P1 ESCALATION"], (3.85, 15))
        self.assertEqual(limits["SPILL"], (4.0, 14))
        self.assertEqual((item["normal"]["low"], item["normal"]["high"]), (1.0, 2.4))

    def test_priority_convention_page_4(self):
        levels = alarm_config.priority_levels()
        self.assertEqual(levels["P1"]["acknowledge_within_seconds"], 120)
        self.assertEqual(levels["P2"]["acknowledge_within_seconds"], 300)
        self.assertEqual(levels["P3"]["acknowledge_within_seconds"], 1800)

    def test_registry_alarm_threshold_agrees_with_manual(self):
        self.assertEqual(TAG_REGISTRY["LIT-101-WWL"].trip_threshold, 3.2)
        manual = [l["value"] for l in alarm_config.definition_for_tag("LIT-101-WWL")["limits"]]
        self.assertIn(TAG_REGISTRY["LIT-101-WWL"].trip_threshold, manual)

    def test_no_limit_conflicts_remain_and_reporting_never_modifies_the_registry(self):
        before = {t: (e.baseline_min, e.baseline_max, e.trip_threshold) for t, e in TAG_REGISTRY.items()}
        conflicts = alarm_config.config_conflicts()
        # Only simulator noise bands around single-value normals remain (bowl speed 3,200 rpm, 0 % LEL).
        self.assertTrue(all(c["field"] in ("normal_low", "normal_high") for c in conflicts), conflicts)
        self.assertEqual({c["tag"] for c in conflicts}, {"SLD-701-BOWL-RPM", "GAS-601-LEL"})
        self.assertEqual(before, {t: (e.baseline_min, e.baseline_max, e.trip_threshold) for t, e in TAG_REGISTRY.items()})


class TagClassificationTests(unittest.TestCase):
    def test_status_tags_are_not_alarms(self):
        self.assertEqual(alarm_config.classify_tag("P101-RUN", "bool"), "status")
        self.assertEqual(alarm_config.classify_tag("ALM-WW-101-HH", "bool"), "alarm")
        self.assertEqual(alarm_config.classify_tag("P101-FAULT", "bool"), "alarm")
        self.assertEqual(alarm_config.classify_tag("LIT-101-WWL", "float"), "measurement")
        self.assertEqual(alarm_config.classify_tag("BWP-2-SEL-OFF", "string"), "status")

    def test_running_pump_is_not_a_breach_but_stopping_is_evidence(self):
        engine = PrioritizationEngine()
        now = datetime.now(timezone.utc)
        running = engine.evaluate_reading(_reading("P101-RUN", True, now))
        self.assertFalse(running.is_breach)
        stopped = engine.evaluate_reading(_reading("P101-RUN", False, now))
        self.assertTrue(stopped.is_breach)
        self.assertFalse(stopped.is_trip_alarm)


class LimitContextTests(unittest.TestCase):
    def test_high_high_reached_and_margin_to_p1_calculated(self):
        ctx = alarm_config.limit_context("LIT-101-WWL", 3.8)
        self.assertTrue(ctx["applied"])
        self.assertEqual(ctx["highest_exceeded"]["name"], "HIGH-HIGH")
        self.assertEqual(ctx["next_limit"]["name"], "P1 ESCALATION")
        self.assertAlmostEqual(ctx["next_limit"]["margin"], 0.05, places=6)
        self.assertFalse(ctx["p1_escalation_reached"])
        self.assertEqual(ctx["calculated_by"], "deterministic_backend")

    def test_p1_escalation_detected(self):
        ctx = alarm_config.limit_context("LIT-101-WWL", 3.9)
        self.assertTrue(ctx["p1_escalation_reached"])
        self.assertEqual(ctx["highest_exceeded"]["name"], "P1 ESCALATION")

    def test_conditional_p1_is_not_reported_as_unconditional(self):
        ctx = alarm_config.limit_context("GAS-601-PRESS", 39.0)
        self.assertEqual(ctx["highest_exceeded"]["name"], "RELIEF")
        self.assertFalse(ctx["p1_escalation_reached"])
        self.assertTrue(ctx["p1_conditional_reached"])
        self.assertIn("flare is not burning", ctx["p1_condition_text"])

    def test_normal_value(self):
        ctx = alarm_config.limit_context("LIT-101-WWL", 1.7)
        self.assertEqual(ctx["normal_state"], "within_normal")
        self.assertIsNone(ctx["highest_exceeded"])

    def test_missing_and_stale_readings_are_not_evaluated(self):
        self.assertFalse(alarm_config.limit_context("LIT-101-WWL", None)["applied"])
        stale = alarm_config.limit_context("LIT-101-WWL", 3.9, data_quality="STALE")
        self.assertFalse(stale["applied"])
        self.assertIn("STALE", stale["reason"])

    def test_parameter_without_sop_limit_returns_none(self):
        # The SOP sets no limit for wet-well inflow (incident map: 610 m³/h, rain).
        self.assertIsNone(alarm_config.limit_context("FIT-101-IN", 610.0))

    def test_low_direction_limit(self):
        ctx = alarm_config.limit_context("RAS-FLOW", 410.0)
        self.assertEqual(ctx["highest_exceeded"]["name"], "LOW")


class AlarmRepeatAndLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(db_path=Path(self.tmp.name) / "t.db")
        get_lifecycle_manager().clear_all()
        self.engine = DeduplicationEngine(db=self.db)
        self.t0 = datetime.now(timezone.utc) - timedelta(minutes=5)

    def tearDown(self):
        get_lifecycle_manager().clear_all()
        self.tmp.cleanup()

    def test_periodic_samples_of_an_active_alarm_are_not_repeats(self):
        for i in range(10):
            reading = _reading("ALM-WW-101-HH", True, self.t0 + timedelta(seconds=2 * i))
            self.db.insert_reading(reading)
            candidate = self.engine.process_reading(reading)
        self.assertEqual(candidate.repeat_count, 1)
        alarms = self.db.get_individual_alarms(candidate.event_id)
        self.assertEqual([a["tag"] for a in alarms], ["ALM-WW-101-HH"])
        self.assertEqual(len(self.db.get_alarm_occurrences(alarms[0]["alarm_id"])), 1)

    def test_status_and_measurements_never_become_alarm_records(self):
        for i, (tag, value) in enumerate([("P101-RUN", False), ("LIT-101-WWL", 3.8), ("ALM-WW-101-HH", True)]):
            reading = _reading(tag, value, self.t0 + timedelta(seconds=i))
            candidate = self.engine.process_reading(reading)
        tags = [a["tag"] for a in self.db.get_individual_alarms(candidate.event_id)]
        self.assertEqual(tags, ["ALM-WW-101-HH"])
        self.assertIn("P101-RUN", candidate.clustered_tags)  # still evidence

    def test_return_to_normal_then_reactivation_counts_one_repeat(self):
        mgr = AlarmLifecycleManager()
        _, rec = mgr.check_exact_duplicate("SCADA", "LiftStation-01", "ALM-WW-101-HH", "TRIP", "ACTIVE", True,
                                           now=self.t0, count_repeat=False)
        mgr.check_exact_duplicate("SCADA", "LiftStation-01", "ALM-WW-101-HH", "TRIP", "ACTIVE", True,
                                  now=self.t0 + timedelta(seconds=2), count_repeat=False)
        self.assertEqual(rec.repeat_count, 1)
        mgr.mark_returned_to_normal("ALM-WW-101-HH")
        _, rec = mgr.check_exact_duplicate("SCADA", "LiftStation-01", "ALM-WW-101-HH", "TRIP", "ACTIVE", True,
                                           now=self.t0 + timedelta(seconds=10), count_repeat=False)
        self.assertEqual(rec.repeat_count, 2)

    def test_out_of_order_false_sample_is_not_a_return_to_normal(self):
        mgr = AlarmLifecycleManager()
        mgr.check_exact_duplicate("SCADA", "LiftStation-01", "P101-FAULT", "TRIP", "ACTIVE", True,
                                  now=self.t0 + timedelta(seconds=10), count_repeat=False)
        mgr.mark_returned_to_normal("P101-FAULT", _ts(self.t0 + timedelta(seconds=8)))  # older sample
        _, rec = mgr.check_exact_duplicate("SCADA", "LiftStation-01", "P101-FAULT", "TRIP", "ACTIVE", True,
                                           now=self.t0 + timedelta(seconds=12), count_repeat=False)
        self.assertEqual(rec.repeat_count, 1)

    def test_explicit_reannunciation_is_counted(self):
        first = self.engine.process_reading(_reading("ALM-WW-101-HH", True, self.t0))
        again = self.engine.process_reading(_reading("ALM-WW-101-HH", True, self.t0 + timedelta(seconds=5),
                                                     alarm_state="REANNUNCIATED"))
        self.assertEqual(first.event_id, again.event_id)
        self.assertEqual(again.repeat_count, 2)


class AlarmStateTests(unittest.TestCase):
    """Acknowledgement is not clearing; only the source input clears."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(db_path=Path(self.tmp.name) / "s.db")
        get_lifecycle_manager().clear_all()
        self.engine = DeduplicationEngine(db=self.db)
        self.t0 = datetime.now(timezone.utc) - timedelta(minutes=5)
        reading = _reading("ALM-WW-101-HH", True, self.t0)
        self.db.insert_reading(reading)
        self.candidate = self.engine.process_reading(reading)
        self.alarm_id = self.db.get_individual_alarms(self.candidate.event_id)[0]["alarm_id"]

    def tearDown(self):
        get_lifecycle_manager().clear_all()
        self.tmp.cleanup()

    def _state(self):
        return {r["tag"]: r["state"] for r in alarm_state_rows(self.db, [self.candidate.event_id])}["ALM-WW-101-HH"]

    def test_active_unacknowledged_then_acknowledged_still_active(self):
        self.assertEqual(self._state(), "ACTIVE_UNACK")
        self.db.save_event_story = getattr(self.db, "save_event_story", None)
        conn = self.db._get_connection()
        with conn:
            conn.execute("INSERT INTO event_stories (event_id, steps, causal_label, created_at) VALUES (?, '[]', 'x', ?)",
                         (self.candidate.event_id, _ts(self.t0)))
        self.db.record_alarm_acknowledgement(self.candidate.event_id, self.alarm_id, "tester")
        self.assertEqual(self._state(), "ACTIVE_ACK")
        latest = self.db.get_latest_reading("ALM-WW-101-HH")
        self.assertTrue(latest.value is True)  # acknowledgement did not clear the input

        clear = _reading("ALM-WW-101-HH", False, self.t0 + timedelta(minutes=1))
        self.db.insert_reading(clear)
        self.db.record_alarm_normal_reading(clear.tag, clear.timestamp, clear.data_source)
        self.assertEqual(self._state(), "NORMAL")

    def test_return_to_normal_without_acknowledgement(self):
        clear = _reading("ALM-WW-101-HH", False, self.t0 + timedelta(minutes=1))
        self.db.insert_reading(clear)
        self.db.record_alarm_normal_reading(clear.tag, clear.timestamp, clear.data_source)
        self.assertEqual(self._state(), "RTN_UNACK")


class DataSourceLabelTests(unittest.TestCase):
    UNCONFIGURED = {"source_label": "UNAVAILABLE DATA", "state": "unconfigured", "connected": False}

    def test_simulation_is_never_labelled_plc_disconnected(self):
        self.assertEqual(data_source_state(self.UNCONFIGURED, "running", None, plc_enabled=True)["mode"], "SIMULATED")
        self.assertEqual(data_source_state(self.UNCONFIGURED, "idle", "simulated", plc_enabled=False)["mode"], "SIMULATED")

    def test_enabled_but_unconnected_plc(self):
        self.assertEqual(data_source_state(self.UNCONFIGURED, "idle", None, plc_enabled=True)["mode"], "PLC DISCONNECTED")

    def test_live_and_stale_plc(self):
        self.assertEqual(data_source_state({"source_label": "LIVE PLC DATA"}, "idle", "live_plc", True)["mode"], "LIVE PLC")
        self.assertEqual(data_source_state({"source_label": "STALE DATA"}, "idle", "live_plc", True)["mode"], "STALE")

    def test_no_data(self):
        self.assertEqual(data_source_state(self.UNCONFIGURED, "idle", None, False)["mode"], "NO DATA")


class SopStepTests(unittest.TestCase):
    def test_lift_station_procedure_is_verbatim_with_pages(self):
        from sop_steps import procedure_steps
        result = procedure_steps("SOP-LFT-001")
        self.assertEqual(result["source"], "verbatim_pdf_text")
        steps = result["steps"]
        self.assertEqual(len(steps), 12)
        self.assertEqual(steps[0]["text"], "Acknowledge the HIGH level alarm (3.2 m). Check both pumps’ status, current and pressure on SCADA.")
        self.assertEqual(steps[0]["page"], 14)
        self.assertEqual(steps[10]["text"], "Watch the wet well level fall below 2.4 m. Release the tanker.")
        self.assertEqual(steps[10]["page"], 15)

    def test_every_manual_sop_yields_its_numbered_steps(self):
        from sop_steps import procedure_steps
        expected = {"SOP-GEN-001": 11, "SOP-GEN-002": 9, "SOP-GEN-003": 8, "SOP-GEN-004": 8, "SOP-INL-001": 12,
                    "SOP-LFT-001": 12, "SOP-GEN-005": 8, "SOP-BIO-001": 11, "SOP-BIO-002": 11,
                    "SOP-GAS-001": 11, "SOP-SLD-001": 8, "SOP-LAB-001": 4}
        for sop_id, count in expected.items():
            steps = procedure_steps(sop_id)["steps"]
            self.assertEqual(len(steps), count, sop_id)
            for step in steps:
                self.assertNotIn("Responsibility", step["text"], sop_id)
                self.assertNotIn("Parameter Normal", step["text"], sop_id)


class OperatorBriefPipelineTests(unittest.IsolatedAsyncioTestCase):
    """Wet-well scenario through the real pipeline, with no LLM and no Qdrant."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        get_lifecycle_manager().clear_all()
        self.env = patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "none"})
        self.env.start()
        from orchestrator import OpsLensOrchestrator
        from generator import SyntheticDataGenerator
        self.db = Database(db_path=Path(self.tmp.name) / "brief.db")
        self.orch = OpsLensOrchestrator(db=self.db)
        start = datetime.now(timezone.utc) - timedelta(seconds=90)
        gen = SyntheticDataGenerator(db=self.db, sample_interval=2.0, start_time=start)
        async for reading in gen.run_scenario_async("wet_well_high_level", speed_multiplier=float("inf")):
            await self.orch.process_reading(reading)
        while self.orch._in_flight_tasks:
            await asyncio.gather(*list(self.orch._in_flight_tasks.values()), return_exceptions=True)
        for candidate in self.db.get_candidate_events():
            await self.orch.process_candidate_event(candidate)
        self.event_id = self.db.get_candidate_events()[-1].event_id

    async def asyncTearDown(self):
        self.env.stop()
        get_lifecycle_manager().clear_all()
        await self.orch.stop()
        self.tmp.cleanup()

    async def test_single_incident_with_only_real_alarm_inputs(self):
        self.assertEqual(len(self.db.get_candidate_events()), 1)
        tags = sorted(a["tag"] for a in self.db.get_individual_alarms(self.event_id))
        self.assertEqual(tags, sorted(["ALM-WW-101-H", "ALM-WW-101-HH", "P101-FAULT", "ALM-P102-FLW-LO",
                                       "ALM-P102-DIS-LO", "ALM-P102-CUR-LO"]))
        self.assertNotIn("P101-RUN", tags)
        self.assertNotIn("P102-RUN", tags)
        self.assertEqual(self.db.get_candidate_events()[0].repeat_count, 1)

    async def test_guidance_uses_verbatim_lift_station_steps(self):
        guidance = self.db.get_guidance(event_id=self.event_id)[0]
        self.assertEqual(guidance.cited_sop_id, "SOP-LFT-001")
        self.assertTrue(guidance.next_best_actions[0].startswith("SOP-LFT-001 step 1 (p.14): Acknowledge the HIGH level alarm"))
        self.assertNotIn("Supporting deviations are unavailable", guidance.explanation_text)

    async def test_brief_is_complete_cited_and_llm_free(self):
        from operator_brief import build_operator_brief
        brief = build_operator_brief(self.orch.get_full_event(self.event_id), self.db)
        self.assertFalse(brief["llm_used"])
        self.assertEqual(brief["problem"]["alarm_tag"], "ALM-WW-101-HH")
        self.assertEqual(brief["problem"]["data_source"], "SIMULATED")
        self.assertIn("P101-RUN", brief["problem"]["status_tags_are_not_alarms"])
        self.assertEqual(brief["sop"]["sop_id"], "SOP-LFT-001")
        self.assertEqual(brief["sop"]["approval_label"], "DRAFT / REFERENCE ONLY — NOT APPROVED")
        self.assertEqual(len(brief["safe_inspection_steps"]["steps"]), 12)
        level = next(c for c in brief["supporting_evidence"]["limit_checks"] if c["tag"] == "LIT-101-WWL")
        self.assertEqual(level["value"], 3.85)                       # exact incident-map value
        self.assertEqual(level["highest_exceeded"]["name"], "P1 ESCALATION")
        self.assertTrue(brief["escalation"]["p1_reached"])
        p102 = next(c for c in brief["supporting_evidence"]["limit_checks"] if c["tag"] == "MOT-102-CUR")
        self.assertEqual(p102["highest_exceeded"]["name"], "LOW-LOAD")
        current = next(c for c in brief["supporting_evidence"]["limit_checks"] if c["tag"] == "MOT-101-CUR")
        self.assertFalse(current["applied"])  # 0 A on a tripped pump is not "low load"
        for hypothesis in brief["possible_causes"]:
            self.assertEqual(hypothesis["kind"], "HYPOTHESIS")
        self.assertIn("Watch the wet well level fall below 2.4 m. Release the tanker. (page 15)", brief["verification_criteria"])
        self.assertEqual(brief["resolution"]["state"], "ACTIVE / UNACKNOWLEDGED")
        # Winding temperature is now instrumented (TIT-101-WDG), so it is evidence, not a gap.
        self.assertFalse(any("winding temperature" in m.lower() and "not instrumented" in m for m in brief["missing_evidence"]))
        self.assertTrue(any(c["tag"] == "TIT-101-WDG" and c["highest_exceeded"]["name"] == "TRIP"
                            for c in brief["supporting_evidence"]["limit_checks"]))
        json.dumps(brief)  # serialisable


class ScenarioApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_submission_returns_409_with_details_and_one_incident(self):
        from api.routes import create_app
        from orchestrator import OpsLensOrchestrator
        get_lifecycle_manager().clear_all()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "none"}):
            db = Database(db_path=Path(tmp) / "api.db")
            orch = OpsLensOrchestrator(db=db)
            app = create_app(orchestrator=orch)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                body = {"scenario_id": "wet_well_high_level", "speed_multiplier": 200}
                first = await client.post("/api/scenarios/run", json=body)
                second = await client.post("/api/scenarios/run", json=body)
                self.assertEqual(first.status_code, 200)
                self.assertEqual(second.status_code, 409)
                self.assertEqual(second.json()["detail"]["running_scenario_id"], "wet_well_high_level")
                self.assertEqual((await client.get("/api/datasource")).json()["mode"], "SIMULATED")
                for _ in range(200):
                    status = (await client.get("/api/scenarios/status")).json()
                    if status["status"] not in ("running",):
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual(status["status"], "awaiting_corrective_action")
                self.assertEqual(len(db.get_candidate_events()), 1)
                # Timestamps are never in the future (acknowledgements stay after alarms).
                latest = db.get_latest_reading("ALM-WW-101-HH")
                self.assertLessEqual(datetime.fromisoformat(latest.timestamp.replace("Z", "+00:00")),
                                     datetime.now(timezone.utc) + timedelta(seconds=2))
                brief = (await client.get(f"/api/events/{status['event_id']}/brief")).json()
                self.assertEqual(brief["sop"]["sop_id"], "SOP-LFT-001")
                active = (await client.get("/api/alarms/active")).json()
                self.assertEqual(active["active_total"], 6)
                self.assertEqual((await client.get("/api/alarms/reference")).json()["source_document"]["document_id"], "SOP-MAN-000")
            await orch.stop()
        get_lifecycle_manager().clear_all()


class LocalLlmUnavailableTests(unittest.TestCase):
    def test_absent_ollama_fails_fast_and_reports_clearly(self):
        from edge_slm import call_local_edge_slm, ollama_health
        with patch.dict(os.environ, {"EDGE_LLM_URL": "http://127.0.0.1:9", "OPSLENS_LLM_PROVIDER": "ollama"}):
            started = time.monotonic()
            self.assertIsNone(call_local_edge_slm("{}", timeout=60))
            self.assertLess(time.monotonic() - started, 5.0)
            health = ollama_health()
            self.assertFalse(health["reachable"])
            self.assertIn("ollama serve", health["error"])

    def test_complete_chat_raises_provider_error_not_invented_text(self):
        from llm_provider import ProviderError, complete_chat
        with patch.dict(os.environ, {"EDGE_LLM_URL": "http://127.0.0.1:9", "OPSLENS_LLM_PROVIDER": "ollama"}):
            with self.assertRaises(ProviderError):
                complete_chat("hello")


class DatabaseThreadSafetyTests(unittest.TestCase):
    """Ask OpsLens reads in a worker thread while telemetry is written on the
    event loop. A shared connection raised 'cannot commit - no transaction is
    active'; per-thread connections must not."""

    def test_concurrent_thread_reads_and_writes(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(db_path=Path(tmp) / "threads.db")
            errors = []
            t0 = datetime.now(timezone.utc)

            def writer():
                try:
                    for i in range(300):
                        db.insert_reading(_reading("LIT-101-WWL", 2.0 + i / 1000, t0 + timedelta(milliseconds=i)))
                except Exception as exc:  # pragma: no cover - failure path
                    errors.append(exc)

            def reader():
                try:
                    for _ in range(300):
                        db.get_latest_reading("LIT-101-WWL")
                        db.get_candidate_events()
                except Exception as exc:  # pragma: no cover - failure path
                    errors.append(exc)

            threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            db.close()
            self.assertEqual(errors, [])


class PlantWideSopVisibilityTests(unittest.TestCase):
    def test_plant_wide_manual_is_not_hidden_for_lift_station(self):
        from sop_retriever import _equipment_matches
        manual = {"equipment": "All wastewater process areas", "equipment_type": "Wastewater Treatment"}
        for equipment in ("LiftStation-01", "RASSystem-01", "BiogasSystem-01", "DewateringCentrifuge-01"):
            self.assertTrue(_equipment_matches(manual, equipment), equipment)
        self.assertFalse(_equipment_matches({"equipment": "Compressor-01"}, "Pump-02"))


class KeywordOnlyPdfIngestionTests(unittest.TestCase):
    """Without sentence-transformers/Qdrant an uploaded SOP PDF is still
    stored, marked DRAFT, and searchable with BM25 - and says so."""

    MANUAL = Path(__file__).resolve().parents[1] / "sop_documents" / "ingested_pdfs" / "SOP-MAN-000.0.a26b0b5eb29b.pdf"

    def test_ingestion_falls_back_to_keyword_only(self):
        import pdf_sop_ingestion
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pdf_sop_ingestion, "PDF_DIR", Path(tmp)), \
                patch("sop_retriever.get_embed_model", side_effect=RuntimeError("no model")):
            result = pdf_sop_ingestion.ingest_pdf(
                self.MANUAL.read_bytes(), "manual.pdf",
                {"sop_id": "TEST-KW-001", "title": "Keyword test", "equipment_type": "Wastewater Treatment",
                 "revision": "0"}, store=None)
            self.assertEqual(result["status"], "stored_keyword_only")
            self.assertFalse(result["vector_indexed"])
            self.assertEqual(result["approval_status"], "draft")   # "Draft for review" detected on the cover
            self.assertFalse(result["approved"])
            self.assertTrue(any(p.suffix == ".pdf" for p in Path(tmp).iterdir()))

    def test_scanned_or_invalid_pdf_is_rejected_not_indexed(self):
        import pdf_sop_ingestion
        with self.assertRaises(Exception):
            pdf_sop_ingestion.ingest_pdf(b"%PDF-1.4 broken", "x.pdf", {"sop_id": "X", "title": "X"}, store=None)


if __name__ == "__main__":
    unittest.main()
