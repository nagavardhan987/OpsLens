"""Acceptance checks for the ten primary demonstration scenarios and manual index."""
import unittest

from scenarios import PRIMARY_DEMO_SCENARIOS, get_scenario, list_primary_demo_scenarios
from demo_sop_sections import DEMO_SOP_SECTIONS, load_demo_sop_document
from pdf_sop_ingestion import list_sop_library
from sop_retriever import PRIMARY_DEMO_NO_SPECIFIC_SOP_TAGS, PRIMARY_DEMO_SOPS, SopRetriever
from assistant import build_assistant_response, resolve_event_sop_reference
from tag_registry import TAG_REGISTRY


class FinalDemoScenarioTests(unittest.TestCase):
    def test_exactly_ten_primary_scenarios_are_grouped_seven_and_three(self):
        scenarios = list_primary_demo_scenarios()
        self.assertEqual(len(scenarios), 10)
        self.assertEqual(sum(item["sop_id"] is not None for item in scenarios), 7)
        self.assertEqual(sum(item["sop_id"] is None for item in scenarios), 3)
        self.assertEqual(len(PRIMARY_DEMO_SCENARIOS), 10)
        self.assertEqual([item[0] for item in PRIMARY_DEMO_SCENARIOS], [
            "wet_well_high_level", "screen_differential_pressure", "biological_foam",
            "ras_pump_failure", "biogas_holder_pressure", "centrifuge_capture",
            "monitoring_due", "valve_restriction", "bearing_wear", "filter_sensor_fault",
        ])
        self.assertEqual(next(item for item in scenarios if item["scenario_id"] == "biological_foam")["sop_id"], "SOP-BIO-001")

    def test_all_twelve_manual_procedures_have_actual_pages_and_draft_status(self):
        self.assertEqual(len(DEMO_SOP_SECTIONS), 12)
        documents = {item["sop_id"]: item for item in list_sop_library()}
        for sop_id in DEMO_SOP_SECTIONS:
            with self.subTest(sop_id=sop_id):
                document = load_demo_sop_document(sop_id)
                self.assertIsNotNone(document)
                self.assertFalse(document["approved"])
                self.assertEqual(document["approval_status"], "draft")
                self.assertTrue(document["content_pages"])
                self.assertTrue(all(page["text"].strip() for page in document["content_pages"]))
                self.assertIn(sop_id, documents)
                self.assertEqual(documents[sop_id]["source_pages"], document["source_pages"])
                self.assertTrue(set(document["source_pages"]).issubset(set(DEMO_SOP_SECTIONS[sop_id]["pages"])))
                self.assertFalse(documents[sop_id]["approved"])

    def test_seven_sop_scenario_alarm_tags_map_to_relevant_manual_procedures(self):
        expected = {
            "ALM-WW-101-HH": "SOP-LFT-001", "ALM-SCR-110-DP": "SOP-INL-001",
            "ALM-AER-201-FOAM": "SOP-BIO-001", "ALM-SLB-201-HIGH": "SOP-BIO-002",
            "ALM-GAS-601-HIGH": "SOP-GAS-001", "ALM-SLD-701-CAPTURE": "SOP-SLD-001",
            "ALM-LAB-901-DUE": "SOP-LAB-001",
        }
        self.assertEqual({key: PRIMARY_DEMO_SOPS[key] for key in expected}, expected)

    def test_all_seven_curated_sops_are_retrieved_and_resolve_to_page_cited_source(self):
        retriever = SopRetriever()
        for alarm_tag, sop_id in {
            "ALM-WW-101-HH": "SOP-LFT-001", "ALM-SCR-110-DP": "SOP-INL-001",
            "ALM-AER-201-FOAM": "SOP-BIO-001", "ALM-SLB-201-HIGH": "SOP-BIO-002",
            "ALM-GAS-601-HIGH": "SOP-GAS-001", "ALM-SLD-701-CAPTURE": "SOP-SLD-001",
            "ALM-LAB-901-DUE": "SOP-LAB-001",
        }.items():
            with self.subTest(alarm_tag=alarm_tag):
                match = retriever._retrieve_primary_demo_reference("event-" + alarm_tag, alarm_tag, "demo-area", alarm_tag, False)
                self.assertEqual(match.sop_id, sop_id)
                self.assertEqual(match.retrieval_state, "MATCH_FOUND")
                resolution, sources = resolve_event_sop_reference({"sop_match": match.model_dump(mode="json")})
                self.assertEqual(resolution["status"], "reference_unapproved")
                self.assertTrue(sources)
                self.assertTrue(all(source.get("page") for source in sources))

        for alarm_tag in ("ALM-C01-VB", "ALM-P02-HP", "ALM-FLT-401-SENSOR"):
            with self.subTest(alarm_tag=alarm_tag):
                match = retriever._retrieve_primary_demo_reference("no-match-" + alarm_tag, alarm_tag, "demo-area", alarm_tag, False)
                self.assertEqual(match.retrieval_state, "NO_MATCH")

    def test_three_no_equipment_sop_cases_have_explicit_no_match_alarm_tags(self):
        expected = {"ALM-C01-VB", "ALM-P02-HP", "ALM-FLT-401-SENSOR"}
        self.assertTrue(expected.issubset(PRIMARY_DEMO_NO_SPECIFIC_SOP_TAGS))
        self.assertFalse(expected.intersection(PRIMARY_DEMO_SOPS))

    def test_each_new_simulation_has_distinct_readings_and_never_marks_values_live(self):
        ids = ["biological_foam", "biogas_holder_pressure", "centrifuge_capture", "monitoring_due"]
        expected_tags = ["ALM-AER-201-FOAM", "ALM-GAS-601-HIGH", "ALM-SLD-701-CAPTURE", "ALM-LAB-901-DUE"]
        for scenario_id, alarm_tag in zip(ids, expected_tags):
            with self.subTest(scenario_id=scenario_id):
                scenario = get_scenario(scenario_id)
                values = scenario.get_tag_values(80.0, {})
                self.assertIn(alarm_tag, values)
                self.assertTrue(values[alarm_tag])
                self.assertIn("SIMULATED", scenario.get_ground_truth()["description"].upper())

    def test_all_ten_scenario_state_machines_reach_their_primary_alarm(self):
        for item in list_primary_demo_scenarios():
            with self.subTest(scenario=item["scenario_id"]):
                values = get_scenario(item["scenario_id"]).get_tag_values(85.0, {})
                self.assertIn(item["alarm_id"], values)
                self.assertIs(values[item["alarm_id"]], True)

    def test_five_question_types_get_distinct_incident_scoped_answers_for_all_ten_scenarios(self):
        questions = [
            "What happened before the alarm?",
            "What could have caused the alarm?",
            "What should the operator verify first?",
            "What actions should be taken to resolve this problem?",
            "What additional information is needed to confirm the suspected cause?",
        ]
        for item in list_primary_demo_scenarios():
            with self.subTest(scenario=item["scenario_id"]):
                scenario = get_scenario(item["scenario_id"])
                alarm = item["alarm_id"]
                signal = next((tag for tag in scenario.expected_correlations if tag != alarm and not tag.startswith("ALM-")), alarm)
                event = {
                    "event_id": f"event-{item['scenario_id']}", "trigger_timestamp": "2026-11-02T10:00:00Z",
                    "candidate": {"primary_tag": alarm, "alarm_id": alarm, "trigger_timestamp": "2026-11-02T10:00:00Z"},
                    "correlated": {"equipment_id": item["equipment_id"]},
                    "story": {"causal_label": item["name"], "steps": [
                        {"tag": signal, "timestamp": "2026-11-02T09:59:00Z", "description": f"{signal} changed in the simulated record", "value_before": 10.0, "value_after": 12.0},
                        {"tag": alarm, "timestamp": "2026-11-02T10:00:00Z", "description": f"{alarm} was recorded active", "value_before": 0, "value_after": 1},
                    ]},
                    "evidence": {"likely_contributor_tag": signal, "confidence_score": 0.65},
                    "runtime_alarm_state": {"active": True, "observed": True},
                }
                entry = TAG_REGISTRY.get(signal)
                unit = entry.unit if entry else ""
                sop_match = SopRetriever()._retrieve_primary_demo_reference(event["event_id"], alarm, item["equipment_id"], alarm, False)
                event["sop_match"] = sop_match.model_dump(mode="json")
                context = {"selected_event": {"timestamp": "2026-11-02T10:00:00Z"}, "missing_data": ["No field inspection observation was recorded."],
                           "window": {"start": "2026-11-02T09:30:00Z", "end": "2026-11-02T10:00:00Z", "duration_minutes": 30},
                           "trend_summaries": [{"tag": signal, "unit": unit, "reading_count": 2,
                               "first_observed": {"value": 10.0, "timestamp": "2026-11-02T09:59:00Z"},
                               "last_observed": {"value": 12.0, "timestamp": "2026-11-02T09:59:30Z"},
                               "absolute_change": 2.0, "percentage_change": 20.0}]}
                answers = [build_assistant_response(event, question, context=context)["question_answer"] for question in questions]
                self.assertTrue(all(answer.strip() for answer in answers))
                self.assertEqual(len(set(answers)), len(questions), "each question type must take its own response path")
                self.assertTrue(all(alarm in answer for answer in answers), "answers must remain bound to the selected alarm")


if __name__ == "__main__":
    unittest.main()
