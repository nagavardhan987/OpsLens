import unittest
from datetime import datetime, timezone

from generator import SyntheticDataGenerator
from models import TagReading
from prioritizer import PrioritizationEngine
from scenarios import get_scenario, list_available_scenarios, list_primary_demo_scenarios
from tag_registry import TAG_REGISTRY


class WastewaterScenarioTests(unittest.TestCase):
    def setUp(self):
        self.nominal = {
            tag: (entry.baseline_min + entry.baseline_max) / 2.0
            for tag, entry in TAG_REGISTRY.items()
            if entry.data_type == "float"
        }
        self.prioritizer = PrioritizationEngine()

    def assert_trip(self, tag, value, active=True):
        entry = TAG_REGISTRY[tag]
        reading = TagReading(
            tag=tag, value=value, timestamp="2026-10-28T00:00:00Z",
            unit=entry.unit, equipment_id=entry.equipment_id,
        )
        assessment = self.prioritizer.evaluate_reading(reading)
        self.assertEqual(assessment.is_breach, active, tag)
        self.assertEqual(assessment.is_trip_alarm, active, tag)

    def test_wastewater_is_first_default_scenario_and_legacy_remains_available(self):
        ids = [item["scenario_id"] for item in list_available_scenarios()]
        self.assertEqual(ids[0], "wet_well_high_level")
        self.assertIn("valve_restriction_cascade", ids)
        self.assertIn("screen_differential_pressure", ids)
        self.assertIn("low_do_ammonia_rise", ids)

    def test_registry_uses_reference_50_mld_flow_scale_and_wastewater_units(self):
        self.assertEqual(TAG_REGISTRY["FIT-101-DIS"].unit, "m³/h")
        nominal_flow = (TAG_REGISTRY["FIT-101-DIS"].baseline_min + TAG_REGISTRY["FIT-101-DIS"].baseline_max) / 2
        self.assertGreater(nominal_flow, 1900)
        self.assertLess(nominal_flow, 2150)
        self.assertEqual(TAG_REGISTRY["AIT-201-DO"].unit, "mg/L")
        self.assertEqual(TAG_REGISTRY["DPT-110-SCR"].unit, "kPa")

    def test_wet_well_scenario_triggers_correlated_high_level_alarm(self):
        scenario = get_scenario("wet_well_high_level")
        values = scenario.get_tag_values(78, self.nominal)
        self.assertGreaterEqual(values["LIT-101-WWL"], 3.6)
        self.assertLess(values["FIT-101-DIS"], 1200.0)
        self.assertLess(values["FIT-101-P1-FLW"], 300.0)
        self.assertFalse(values["P101-RUN"])
        self.assertTrue(values["P101-FAULT"])
        self.assertTrue(values["ALM-WW-101-HH"])
        self.assert_trip("FIT-101-DIS", values["FIT-101-DIS"])
        self.assert_trip("LIT-101-WWL", values["LIT-101-WWL"])
        self.assert_trip("ALM-WW-101-HH", values["ALM-WW-101-HH"])

    def test_screen_differential_pressure_alarm_uses_configured_trip(self):
        values = get_scenario("screen_differential_pressure").get_tag_values(68, self.nominal)
        self.assertGreaterEqual(values["DPT-110-SCR"], 4.0)
        self.assertTrue(values["ALM-SCR-110-DP"])
        self.assertLess(values["FIT-110-IN"], self.nominal["FIT-110-IN"])
        self.assertFalse(values["SCR-110-RAKE-RUN"])
        self.assertGreaterEqual(values["SCR-110-MOT-CUR"], 14.0)
        self.assert_trip("DPT-110-SCR", values["DPT-110-SCR"])
        self.assert_trip("ALM-SCR-110-DP", values["ALM-SCR-110-DP"])

    def test_ras_pump_failure_precedes_high_sludge_blanket_and_trips_both_alarms(self):
        scenario = get_scenario("ras_pump_failure")
        early = scenario.get_tag_values(18, self.nominal)
        late = scenario.get_tag_values(88, self.nominal)
        self.assertFalse(early["RAS-P1-RUN"])
        self.assertEqual(early["RAS-P1-CUR"], 0.0)
        self.assertTrue(early["ALM-RAS-P1-FAIL"])
        self.assertTrue(late["ALM-SLB-201-HIGH"])
        self.assertGreater(late["SLB-201-DEPTH"], 1.5)
        self.assertLess(late["RAS-FLOW"], 550.0)

    def test_filter_sensor_fault_reports_disagreement_quality_and_stale_metadata(self):
        scenario = get_scenario("filter_sensor_fault")
        values = scenario.get_tag_values(28, self.nominal)
        metadata = scenario.get_reading_metadata("FLT-401-PRI-NTU", 28)
        self.assertGreater(values["FLT-401-PRI-NTU"], values["FLT-401-RED-NTU"] * 3)
        self.assertEqual(values["FLT-401-PRI-QUALITY"], "POOR")
        self.assertEqual(values["FLT-401-PRI-COMMS"], "DISCONNECTED")
        self.assertTrue(values["ALM-FLT-401-SENSOR"])
        self.assertEqual(metadata["data_quality"], "STALE")
        self.assertEqual(metadata["connection_status"], "disconnected")

    def test_primary_demo_registry_contains_exact_ten_scenarios_in_two_groups(self):
        scenarios = list_primary_demo_scenarios()
        self.assertEqual(len(scenarios), 10)
        self.assertEqual([item["demo_group"] for item in scenarios], ["WITH MATCHING SOP"] * 7 + ["WITHOUT SPECIFIC EQUIPMENT-FAILURE SOP"] * 3)
        self.assertEqual([item["sop_id"] for item in scenarios[:7]], ["SOP-LFT-001", "SOP-INL-001", "SOP-BIO-001", "SOP-BIO-002", "SOP-GAS-001", "SOP-SLD-001", "SOP-LAB-001"])
        self.assertTrue(all(item["sop_id"] is None for item in scenarios[7:]))
        self.assertTrue(all(item["source_status"] == "SIMULATED" for item in scenarios))

    def test_primary_demo_sops_resolve_to_manual_pages_and_remain_draft(self):
        from demo_sop_sections import load_demo_sop_document
        from assistant import resolve_event_sop_reference
        for sop_id, phrase in [
            ("SOP-LFT-001", "Wet well level"),
            ("SOP-INL-001", "Bar Screen Operation"),
            ("SOP-BIO-002", "RAS Pump Failure"),
        ]:
            with self.subTest(sop_id=sop_id):
                document = load_demo_sop_document(sop_id)
                self.assertIsNotNone(document)
                self.assertFalse(document["approved"])
                self.assertEqual(document["revision"], "0")
                joined = "\n".join(page["text"] for page in document["content_pages"])
                self.assertIn(phrase.casefold(), joined.casefold())
                resolution, sources = resolve_event_sop_reference({"sop_match": {
                    "sop_id": sop_id, "sop_title": document["title"], "revision": "0",
                    "retrieved_chunks": [{"sop_id": sop_id, "document_id": sop_id,
                        "text": document["content_pages"][-1]["text"], "page": document["content_pages"][-1]["page"]}],
                }})
                self.assertEqual(resolution["status"], "reference_unapproved")
                self.assertTrue(sources)
                self.assertFalse(sources[0]["approved"])
                self.assertIn("not approved", sources[0]["document_status"].casefold())

    def test_primary_demo_without_sop_never_returns_a_fake_equipment_procedure(self):
        from sop_retriever import SopRetriever
        retriever = SopRetriever()
        for equipment, tag in [("Compressor-01", "ALM-C01-VB"), ("Pump-02", "ALM-P02-HP"), ("Filter-01", "ALM-FLT-401-SENSOR")]:
            with self.subTest(equipment=equipment):
                result = retriever._retrieve_primary_demo_reference("demo-event", tag, equipment, "test", False)
                self.assertEqual(result.sop_id, "SOP-NONE")
                self.assertEqual(result.retrieval_status, "no_match")
                self.assertIn("No specific applicable", result.why_retrieved["message"])

    def test_low_do_precedes_ammonia_alarm_in_synthetic_sequence(self):
        scenario = get_scenario("low_do_ammonia_rise")
        earlier = scenario.get_tag_values(56, self.nominal)
        later = scenario.get_tag_values(82, self.nominal)
        self.assertTrue(earlier["ALM-AER-201-DO"])
        self.assertFalse(earlier["ALM-AER-201-NH4"])
        self.assertTrue(later["ALM-AER-201-NH4"])
        self.assertLess(later["AIT-201-DO"], 1.0)
        self.assertGreaterEqual(later["AIT-201-NH4"], 8.0)
        self.assert_trip("AIT-201-DO", later["AIT-201-DO"])
        self.assert_trip("AIT-201-NH4", later["AIT-201-NH4"])
        self.assert_trip("ALM-AER-201-DO", later["ALM-AER-201-DO"])
        self.assert_trip("ALM-AER-201-NH4", later["ALM-AER-201-NH4"])

    def test_scenario_7_uses_simulated_filter_and_uv_reference_values(self):
        scenario = get_scenario("filters_uv_disinfection_failure")
        values = scenario.get_tag_values(92, self.nominal)
        truth = scenario.get_ground_truth()

        self.assertEqual(scenario.name, "Scenario 7 — Filters Clog and UV Disinfection Fails")
        self.assertEqual(truth["source_status"], "SIMULATED / REFERENCE ONLY")
        self.assertAlmostEqual(values["FLT-401-BW-HOURS"], 41.0)
        self.assertAlmostEqual(values["FLT-401-HL"], 2.9)
        self.assertAlmostEqual(values["FLT-401-TURB"], 6.8)
        self.assertAlmostEqual(values["UV-501-UVT"], 48.0)
        self.assertEqual(values["UV-501-LAMPS-ON"], 18)
        self.assertAlmostEqual(values["UV-501-DOSE"], 14.0)
        self.assertTrue(values["ALM-UV-501-DOSE-LOW"])
        self.assertEqual(values["RLV-501-CLOSED"], "CLOSED")
        self.assertEqual(values["CHL-501-BACKUP-STATUS"], "ACTIVE — simulated backup status")
        self.assertEqual(
            truth["missing_sops"],
            ["SOP-TER-001", "SOP-DIS-001", "SOP-DIS-002", "SOP-CHM-001", "SOP-EFF-001", "SOP-LAB-002"],
        )

    def test_generator_persists_wastewater_readings_and_alarm_inputs(self):
        class ReadingSink:
            def __init__(self):
                self.readings = []

            def insert_reading(self, reading):
                self.readings.append(reading)

        cases = [
            ("wet_well_high_level", 78.0, "ALM-WW-101-HH"),
            ("screen_differential_pressure", 68.0, "ALM-SCR-110-DP"),
            ("ras_pump_failure", 88.0, "ALM-SLB-201-HIGH"),
            ("bearing_wear", 78.0, "ALM-C01-VB"),
            ("valve_restriction", 72.0, "ALM-P02-HP"),
            ("filter_sensor_fault", 28.0, "ALM-FLT-401-SENSOR"),
        ]
        for scenario_id, elapsed, alarm_tag in cases:
            with self.subTest(scenario=scenario_id):
                sink = ReadingSink()
                generator = SyntheticDataGenerator(
                    db=sink, sample_interval=2.0,
                    start_time=datetime(2026, 10, 28, tzinfo=timezone.utc),
                )
                generator.current_scenario = get_scenario(scenario_id)
                generator.scenario_elapsed = elapsed
                sample = generator.advance_step()
                by_tag = {reading.tag: reading for reading in sample}
                self.assertIs(by_tag[alarm_tag].value, True)
                self.assertTrue(all(reading.data_source == "simulated" for reading in sink.readings))
                self.assertEqual(len(sink.readings), len(TAG_REGISTRY))
                self.assertEqual(sink.readings[-1].timestamp, by_tag[sink.readings[-1].tag].timestamp)

    def test_filter_sensor_fault_generator_labels_stale_reading_and_receipt_time(self):
        class ReadingSink:
            def __init__(self): self.readings = []
            def insert_reading(self, reading): self.readings.append(reading)
        sink = ReadingSink()
        generator = SyntheticDataGenerator(db=sink, sample_interval=2.0,
            start_time=datetime(2026, 10, 28, tzinfo=timezone.utc))
        generator.current_scenario = get_scenario("filter_sensor_fault")
        generator.scenario_elapsed = 28.0
        by_tag = {reading.tag: reading for reading in generator.advance_step()}
        primary = by_tag["FLT-401-PRI-NTU"]
        self.assertEqual(primary.data_source, "simulated")
        self.assertEqual(primary.data_quality, "STALE")
        self.assertEqual(primary.connection_status, "disconnected")
        self.assertEqual(primary.received_timestamp, "2026-10-28T00:00:00Z")
        self.assertEqual(primary.timestamp, "2026-10-27T23:58:30Z")


if __name__ == "__main__":
    unittest.main()
