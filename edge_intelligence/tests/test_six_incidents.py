"""The six Scenario Lab incidents: exact values, tag ownership, isolation,
timestamps, SOP mapping/coverage, recovery and start/stop.

Values are checked against the supplied incident map ("Wastewater plant: six
incidents on one map"); limits against SOP-MAN-000.
"""
import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

import incident_catalog as catalog
from alarm_lifecycle import get_lifecycle_manager
from database import Database
from generator import SyntheticDataGenerator
from tag_registry import TAG_REGISTRY, LEGACY_EQUIPMENT

# Incident-map values: (tag, incident value, after-fix value)
EXACT = {
    "screen_differential_pressure": [("LDT-110-SCR", 52, 9), ("LIT-110-CH", 1.65, 1.0), ("FIT-110-IN", 2150, 1480),
                                     ("SCR-110-MOT-CUR", 0.0, 7.5), ("SCR-110-SCREENINGS", 0.0, 0.3)],
    "wet_well_high_level": [("LIT-101-WWL", 3.85, 1.6), ("FIT-101-IN", 610, 480), ("TIT-101-WDG", 118, 68),
                            ("MOT-101-CUR", 0, 31), ("PIT-102-DIS", 1.1, 3.1), ("FIT-102-FLW", 90, 420),
                            ("MOT-102-CUR", 19, 32)],
    "biological_foam": [("AER-201-SLUDGE-AGE", 21, 11), ("AER-201-WAS-FLOW", 70, 260), ("AER-201-MLSS", 5100, 3300),
                        ("AER-201-FM", 0.09, 0.28), ("AIT-201-DO", 2.4, 2.2), ("AER-201-FOAM-DEPTH", 45, 4),
                        ("EFF-301-TURB", 8.8, 3.5), ("EFF-301-TSS", 26, 11)],
    "ras_pump_failure": [("RAS-FLOW", 410, 760), ("RAS-P1-FLOW", 0, 390), ("TIT-RAS-P1-WDG", 142, 72),
                         ("SLB-201-DEPTH", 2.1, 0.6), ("CLR-201-SLR", 7.4, 4.2), ("AER-201-MLSS", 1900, 3000),
                         ("EFF-301-TSS", 24, 12)],
    "biogas_holder_pressure": [("GAS-601-PRESS", 36, 22), ("GAS-601-FILL", 96, 60), ("GAS-601-PROD", 185, 180),
                               ("CHP-601-GAS", 0, 170), ("CHP-601-KWE", 0, 400), ("FLR-601-FLOW", 185, 0),
                               ("GAS-601-LEL", 4, 0)],
    "centrifuge_capture": [("SLD-701-BOWL-RPM", 2400, 3200), ("SLD-701-POLYMER", 4, 10), ("SLD-701-CAPTURE", 74, 94),
                           ("SLD-701-CAKE-DRY", 16, 24), ("SLD-701-CENTRATE-NH4", 1650, 950), ("INL-110-NH4", 56, 41),
                           ("AER-201-AIRFLOW", 4050, 3300), ("EFF-301-NH4", 3.8, 1.2)],
}
SOPS = {"screen_differential_pressure": "SOP-INL-001", "wet_well_high_level": "SOP-LFT-001",
        "biological_foam": "SOP-BIO-001", "ras_pump_failure": "SOP-BIO-002",
        "biogas_holder_pressure": "SOP-GAS-001", "centrifuge_capture": "SOP-SLD-001"}


def run_generator(scenario_id, recover=False):
    tmp = tempfile.mkdtemp()
    db = Database(db_path=Path(tmp) / "g.db")
    gen = SyntheticDataGenerator(db=db, sample_interval=2.0, start_time=datetime(2026, 11, 4, tzinfo=timezone.utc))
    readings = list(gen.run_scenario(scenario_id, speed_multiplier=float("inf")))
    recovered = []
    if recover:
        async def _rec():
            return [r async for r in gen.run_recovery_async(speed_multiplier=float("inf"))]
        recovered = asyncio.run(_rec())
    return readings, recovered


def last_values(readings):
    out = {}
    for r in readings:
        out[r.tag] = r.value
    return out


class CatalogTests(unittest.TestCase):
    def test_six_scenarios_named_as_in_the_incident_map(self):
        self.assertEqual([s.name for s in catalog.SCENARIOS], [
            "Rags jam the bar screen", "The lift station pumps clog", "Nocardia foam on the aeration tank",
            "RAS pump fails, sludge blanket rises", "CHP engine trips, gas holder fills", "Centrate poisons the plant inlet"])
        self.assertNotIn("overview", " ".join(s.scenario_id for s in catalog.SCENARIOS))

    def test_every_tag_has_one_equipment_owner_matching_the_registry(self):
        for tag, sig in catalog.plant_signals().items():
            self.assertEqual(TAG_REGISTRY[tag].equipment_id, sig.equipment_id, tag)
            self.assertEqual(TAG_REGISTRY[tag].unit, sig.unit, tag)
        for spec in catalog.SCENARIOS:
            for tag in catalog.scenario_tags(spec):
                self.assertIn(tag, TAG_REGISTRY, tag)
                self.assertNotIn(TAG_REGISTRY[tag].equipment_id, LEGACY_EQUIPMENT, tag)

    def test_lift_station_and_pump02_tags_never_share_equipment(self):
        lift = catalog.SCENARIO_BY_ID["wet_well_high_level"]
        lift_tags = set(catalog.scenario_tags(lift))
        pump02_tags = {t for t, e in TAG_REGISTRY.items() if e.equipment_id == "Pump-02"}
        self.assertFalse(lift_tags & pump02_tags)
        self.assertTrue(all(TAG_REGISTRY[t].equipment_id == "LiftStation-01" for t in lift_tags))

    def test_frontend_tag_map_matches_the_catalog(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("gen", Path(__file__).resolve().parent.parent / "tools" / "gen_frontend_tags.py")
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        self.assertEqual(gen.OUT.read_text(encoding="utf-8"), gen.render(),
                         "Run python tools/gen_frontend_tags.py")

    def test_generic_pump_words_on_lift_station_do_not_point_at_pump02(self):
        from assistant import detect_incident_mismatch
        for q in ("Why is the pump discharge pressure low and the motor current dropping?",
                  "Is P-102 clogged? Check pump flow and motor current.",
                  "What should I check on the pumps before restarting P-101?"):
            mismatch = detect_incident_mismatch("LiftStation-01", "ALM-WW-101-HH", [], q)
            self.assertFalse(mismatch and mismatch.get("foreign_equipment") == "Pump-02", (q, mismatch))

    def test_sop_mapping_and_draft_status(self):
        for spec in catalog.SCENARIOS:
            summary = catalog.scenario_summary(spec)
            self.assertEqual(summary["sop_id"], SOPS[spec.scenario_id])
            self.assertIn("NOT APPROVED", summary["sop_approval_status"])
            self.assertEqual(summary["source_status"], "SIMULATED")

    def test_only_centrate_incident_is_partial_and_names_the_toxicity_gap(self):
        partial = [s.scenario_id for s in catalog.SCENARIOS if s.sop_coverage == "partial"]
        self.assertEqual(partial, ["centrifuge_capture"])
        notes = " ".join(catalog.SCENARIO_BY_ID["centrifuge_capture"].sop_coverage_notes).lower()
        self.assertIn("inhibitory or toxic", notes)

    def test_sop_sld_001_text_really_lacks_toxicity_and_inhibition_content(self):
        from demo_sop_sections import load_demo_sop_document
        text = " ".join(p["text"] for p in load_demo_sop_document("SOP-SLD-001")["content_pages"]).lower()
        self.assertIn("ammonia", text)
        for word in ("toxic", "inhibit", "nitrif"):
            self.assertNotIn(word, text)


class TelemetryTests(unittest.TestCase):
    def test_incident_and_after_fix_values_are_exact(self):
        for scenario_id, rows in EXACT.items():
            readings, recovered = run_generator(scenario_id, recover=True)
            incident, after = last_values(readings), last_values(recovered)
            for tag, incident_value, after_value in rows:
                with self.subTest(scenario=scenario_id, tag=tag):
                    self.assertAlmostEqual(float(incident[tag]), incident_value, places=3)
                    self.assertAlmostEqual(float(after[tag]), after_value, places=3)

    def test_normal_period_values_are_inside_the_normal_range(self):
        for spec in catalog.SCENARIOS:
            readings, _ = run_generator(spec.scenario_id)
            first = {}
            for r in readings:
                first.setdefault(r.tag, r.value)
            for sig in spec.signals:
                lo, hi = sig.noise_band or sig.normal
                with self.subTest(scenario=spec.scenario_id, tag=sig.tag):
                    self.assertGreaterEqual(float(first[sig.tag]), float(lo) - 1e-9)
                    self.assertLessEqual(float(first[sig.tag]), float(hi) + 1e-9)

    def test_alarms_raise_during_incident_and_clear_after_recovery(self):
        for spec in catalog.SCENARIOS:
            readings, recovered = run_generator(spec.scenario_id, recover=True)
            with self.subTest(scenario=spec.scenario_id):
                self.assertIs(last_values(readings)[spec.primary_alarm], True)
                after = last_values(recovered)
                active = [t for t in catalog.scenario_tags(spec) if t in catalog.alarm_inputs() and after.get(t) is True]
                self.assertEqual(active, [])

    def test_timestamps_strictly_increase_and_data_is_marked_simulated(self):
        readings, recovered = run_generator("wet_well_high_level", recover=True)
        per_tag = {}
        for r in readings + recovered:
            per_tag.setdefault(r.tag, []).append(r.timestamp)
            self.assertEqual(r.data_source, "simulated")
            self.assertEqual(r.connection_status, "simulation")
        for tag, stamps in per_tag.items():
            self.assertEqual(stamps, sorted(stamps), tag)
            self.assertEqual(len(stamps), len(set(stamps)), tag)

    def test_causal_order_of_the_lift_station_sequence(self):
        readings, _ = run_generator("wet_well_high_level")
        first_true = {}
        for r in readings:
            if r.value is True and r.tag not in first_true:
                first_true[r.tag] = r.timestamp
        self.assertLess(first_true["ALM-P102-FLW-LO"], first_true["P101-FAULT"])
        self.assertLess(first_true["P101-FAULT"], first_true["ALM-WW-101-H"])
        self.assertLess(first_true["ALM-WW-101-H"], first_true["ALM-WW-101-HH"])

    def test_wastewater_runs_emit_no_legacy_equipment(self):
        for spec in catalog.SCENARIOS:
            readings, _ = run_generator(spec.scenario_id)
            self.assertFalse({r.equipment_id for r in readings} & set(LEGACY_EQUIPMENT), spec.scenario_id)


class PipelineIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        get_lifecycle_manager().clear_all()
        self.env = patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "none"})
        self.env.start()
        from orchestrator import OpsLensOrchestrator
        self.db = Database(db_path=Path(self.tmp.name) / "p.db")
        self.orch = OpsLensOrchestrator(db=self.db)

    async def asyncTearDown(self):
        self.env.stop()
        await self.orch.stop()
        get_lifecycle_manager().clear_all()
        self.tmp.cleanup()

    async def _drain(self):
        while self.orch._in_flight_tasks:
            await asyncio.gather(*list(self.orch._in_flight_tasks.values()), return_exceptions=True)

    async def _run(self, scenario_id, start):
        before = {c.event_id for c in self.db.get_candidate_events()}
        gen = SyntheticDataGenerator(db=self.db, sample_interval=2.0, start_time=start)
        async for reading in gen.run_scenario_async(scenario_id, speed_multiplier=float("inf")):
            await self.orch.process_reading(reading)
        await self._drain()
        for c in self.db.get_candidate_events():
            if c.event_id not in before:
                await self.orch.process_candidate_event(c)
        await self._drain()
        return [c for c in self.db.get_candidate_events() if c.event_id not in before]

    async def test_each_incident_retrieves_only_its_sop_and_its_own_telemetry(self):
        from operator_brief import build_operator_brief
        start = datetime.now(timezone.utc) - timedelta(hours=3)
        for index, spec in enumerate(catalog.SCENARIOS):
            new = await self._run(spec.scenario_id, start + timedelta(minutes=20 * index))
            with self.subTest(scenario=spec.scenario_id):
                self.assertEqual(len(new), 1, [c.primary_tag for c in new])
                event = self.orch.get_full_event(new[0].event_id)
                self.assertEqual(event["primary_tag"], spec.primary_alarm)
                own = set(catalog.scenario_tags(spec))
                self.assertTrue(set(event["candidate"]["clustered_tags"]) <= own,
                                set(event["candidate"]["clustered_tags"]) - own)
                self.assertEqual(event["sop_match"]["sop_id"], spec.sop_id)
                chunk_sops = {c.get("sop_id") for c in event["sop_match"]["retrieved_chunks"]}
                self.assertEqual(chunk_sops, {spec.sop_id})
                brief = build_operator_brief(event, self.db)
                self.assertTrue({c["tag"] for c in brief["supporting_evidence"]["limit_checks"]} <= own)
                self.assertEqual(brief["sop"]["coverage"], spec.sop_coverage)
                self.assertFalse(brief["sop"]["approved"])

    async def test_lift_station_cannot_receive_pump02_evidence(self):
        """Pump-02 readings interleaved at the same timestamps must not join
        the LiftStation-01 incident, its brief or its AI facts."""
        start = datetime.now(timezone.utc) - timedelta(minutes=10)
        lift_gen = SyntheticDataGenerator(db=self.db, sample_interval=2.0, start_time=start)
        pump_gen = SyntheticDataGenerator(db=self.db, sample_interval=2.0, start_time=start)
        lift = lift_gen.run_scenario("wet_well_high_level", speed_multiplier=float("inf"))
        pump = pump_gen.run_scenario("valve_restriction", speed_multiplier=float("inf"))
        pump_readings = [r for r in pump if r.equipment_id == "Pump-02"]
        for reading in lift:
            await self.orch.process_reading(reading)
            if pump_readings:
                await self.orch.process_reading(pump_readings.pop(0))
        for reading in pump_readings:
            await self.orch.process_reading(reading)
        await self._drain()
        for c in self.db.get_candidate_events():
            await self.orch.process_candidate_event(c)
        await self._drain()
        lift_events = [c for c in self.db.get_candidate_events() if c.primary_tag == "ALM-WW-101-HH"]
        pump_events = [c for c in self.db.get_candidate_events() if c.primary_tag == "ALM-P02-HP"]
        self.assertEqual(len(lift_events), 1)
        self.assertEqual(len(pump_events), 1)
        pump_tags = {t for t, e in TAG_REGISTRY.items() if e.equipment_id == "Pump-02"}
        event = self.orch.get_full_event(lift_events[0].event_id)
        self.assertFalse(set(event["candidate"]["clustered_tags"]) & pump_tags)
        self.assertFalse({s["tag"] for s in event["story"]["steps"]} & pump_tags)
        self.assertNotIn(event["evidence"]["likely_contributor_tag"], pump_tags)
        from operator_brief import build_operator_brief
        brief = build_operator_brief(event, self.db)
        brief_tags = {c["tag"] for c in brief["supporting_evidence"]["limit_checks"]} | \
                     {o["tag"] for o in brief["supporting_evidence"]["observed"]}
        self.assertFalse(brief_tags & pump_tags)
        from ai_diagnosis import build_facts
        facts = build_facts(event, self.db)
        self.assertFalse(set(facts["incident_tags"]) & pump_tags)
        self.assertNotIn("PIT-02-PRS", str(facts))
        self.assertNotIn("Pump-02", str(facts))


class ScenarioStartStopApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_stop_details_and_recovery(self):
        from api.routes import create_app
        from orchestrator import OpsLensOrchestrator
        get_lifecycle_manager().clear_all()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "none"}):
            db = Database(db_path=Path(tmp) / "api.db")
            orch = OpsLensOrchestrator(db=db)
            app = create_app(orchestrator=orch)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                listed = (await client.get("/api/scenarios")).json()["scenarios"]
                self.assertEqual(len(listed), 6)
                details = (await client.get("/api/scenarios/centrifuge_capture/details")).json()
                self.assertEqual(details["sop_coverage"], "partial")
                self.assertEqual(len(details["table"]), 8)
                legacy = await client.post("/api/scenarios/run", json={"scenario_id": "valve_restriction"})
                self.assertEqual(legacy.status_code, 400)

                # Start, then stop part-way.
                self.assertEqual((await client.post("/api/scenarios/run", json={"scenario_id": "biological_foam", "speed_multiplier": 20})).status_code, 200)
                await asyncio.sleep(0.3)
                self.assertEqual((await client.post("/api/scenarios/stop")).status_code, 200)
                for _ in range(100):
                    status = (await client.get("/api/scenarios/status")).json()
                    if status["status"] != "running":
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual(status["status"], "stopped")
                self.assertEqual((await client.post("/api/scenarios/stop")).status_code, 409)

                # Full run, then simulated corrective action clears the alarm input.
                await client.post("/api/scenarios/run", json={"scenario_id": "wet_well_high_level", "speed_multiplier": 400})
                for _ in range(200):
                    status = (await client.get("/api/scenarios/status")).json()
                    if status["status"] not in ("running",):
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual(status["status"], "awaiting_corrective_action")
                self.assertEqual(status["alarm_tag"], "ALM-WW-101-HH")
                self.assertEqual(status["progress"], 1.0)
                trends = (await client.get(f"/api/events/{status['event_id']}/trends")).json()
                spec = catalog.SCENARIO_BY_ID["wet_well_high_level"]
                self.assertEqual([s["tag"] for s in trends["signals"]], [s.tag for s in spec.signals])
                level = next(s for s in trends["signals"] if s["tag"] == "LIT-101-WWL")
                self.assertEqual(level["latest"], 3.85)
                self.assertIsNotNone(level["beyond_limit"])
                self.assertLessEqual(len(level["points"]), 48)
                self.assertEqual([p["t"] for p in level["points"]], sorted(p["t"] for p in level["points"]))
                self.assertEqual(level["data_source"], "simulated")
                recovered = await client.post("/api/scenarios/corrective-action")
                self.assertEqual(recovered.status_code, 200, recovered.text)
                self.assertFalse(recovered.json()["alarm_active"])
                self.assertEqual(db.get_latest_reading("LIT-101-WWL").value, 1.6)
                first_event = status["event_id"]

                # Same scenario again while its incident is still open: the
                # recurrence joins that incident (repeat count), and the run
                # reports it instead of "no incident".
                await client.post("/api/scenarios/run", json={"scenario_id": "wet_well_high_level", "speed_multiplier": 400})
                for _ in range(200):
                    status = (await client.get("/api/scenarios/status")).json()
                    if status["status"] not in ("running",):
                        break
                    await asyncio.sleep(0.05)
                full = orch.get_full_event(first_event)
                self.assertEqual(status["status"], "awaiting_corrective_action",
                                 (status, full.get("status"), [(a.get("tag"), a.get("lifecycle_state"), a.get("repeat_count"), a.get("last_seen_timestamp")) for a in full.get("individual_alarms") or []],
                                  [(c.event_id[:8], c.primary_tag) for c in db.get_candidate_events()]))
                self.assertEqual(status["stage"], "incident_repeated")
                self.assertEqual(status["event_id"], first_event)
                self.assertEqual(status["repeat_count"], 2)

                # Still active (no fix applied): a third start is refused with the reason.
                again = await client.post("/api/scenarios/run", json={"scenario_id": "wet_well_high_level", "speed_multiplier": 400})
                self.assertEqual(again.status_code, 409)
                self.assertEqual(again.json()["detail"]["stage"], "alarm_still_active")
                self.assertEqual((await client.get("/api/scenarios/status")).json()["status"], "awaiting_corrective_action")
            await orch.stop()
        get_lifecycle_manager().clear_all()


if __name__ == "__main__":
    unittest.main()


class BackToBackRunsTests(unittest.IsolatedAsyncioTestCase):
    async def test_back_to_back_runs_never_merge_incidents(self):
        """Regression: RAS alarms once joined the still-open foam incident
        (shared AER-201-MLSS / EFF-301-TSS and the 90 s clustering window)."""
        from api.routes import create_app
        from orchestrator import OpsLensOrchestrator
        get_lifecycle_manager().clear_all()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "none"}):
            db = Database(db_path=Path(tmp) / "b2b.db")
            orch = OpsLensOrchestrator(db=db)
            app = create_app(orchestrator=orch)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                seen_events = set()
                for spec in catalog.SCENARIOS:
                    r = await client.post("/api/scenarios/run", json={"scenario_id": spec.scenario_id, "speed_multiplier": 400})
                    self.assertEqual(r.status_code, 200, r.text)
                    for _ in range(300):
                        status = (await client.get("/api/scenarios/status")).json()
                        if status["status"] != "running":
                            break
                        await asyncio.sleep(0.05)
                    with self.subTest(scenario=spec.scenario_id):
                        self.assertEqual(status["stage"], "incident_published", status)
                        self.assertNotIn(status["event_id"], seen_events)
                        seen_events.add(status["event_id"])
                        event = orch.get_full_event(status["event_id"])
                        self.assertEqual(event["primary_tag"], spec.primary_alarm)
                        own = set(catalog.scenario_tags(spec))
                        alarm_tags = {a["tag"] for a in event["individual_alarms"]}
                        self.assertTrue(alarm_tags <= own, alarm_tags - own)
                        self.assertTrue(set(event["candidate"]["clustered_tags"]) <= own)
                        # Regression: the previous run's after-fix readings were
                        # stamped later than this run, so "latest" showed normal.
                        self.assertIs(db.get_latest_reading(spec.primary_alarm).value, True)
                        brief = (await client.get(f"/api/events/{status['event_id']}/brief")).json()
                        self.assertTrue(brief["resolution"]["alarm_input_active"], brief["resolution"])
                    fixed = await client.post("/api/scenarios/corrective-action")
                    self.assertEqual(fixed.status_code, 200, fixed.text)
                # Round 2 after the earlier clusters expired: each recurrence
                # is a new incident that owns its primary alarm row; the old
                # incident's record is not re-activated.
                orch.dedup.seal_clusters()  # as if the 10-minute cluster lifetime had passed
                if True:
                    for spec in catalog.SCENARIOS:
                        r = await client.post("/api/scenarios/run", json={"scenario_id": spec.scenario_id, "speed_multiplier": 400})
                        self.assertEqual(r.status_code, 200, r.text)
                        for _ in range(300):
                            status = (await client.get("/api/scenarios/status")).json()
                            if status["status"] != "running":
                                break
                            await asyncio.sleep(0.05)
                        with self.subTest(round=2, scenario=spec.scenario_id):
                            self.assertEqual(status["stage"], "incident_published", status)
                            self.assertNotIn(status["event_id"], seen_events)
                            event = orch.get_full_event(status["event_id"])
                            primary = [a for a in event["individual_alarms"] if a["tag"] == spec.primary_alarm]
                            self.assertEqual(len(primary), 1, [a["tag"] for a in event["individual_alarms"]])
                            self.assertEqual(primary[0]["lifecycle_state"], "ACTIVE")
                            self.assertEqual(primary[0]["repeat_count"], 1)
                        await client.post("/api/scenarios/corrective-action")
                # Earlier incidents kept only their own alarms.
                for spec in catalog.SCENARIOS:
                    own = set(catalog.scenario_tags(spec))
                    for cand in db.get_candidate_events():
                        if cand.primary_tag == spec.primary_alarm:
                            tags = {a["tag"] for a in db.get_individual_alarms(cand.event_id)}
                            self.assertTrue(tags <= own, (spec.scenario_id, tags - own))
            await orch.stop()
        get_lifecycle_manager().clear_all()
