import unittest

from assistant import _structured_assessment
from scenarios import get_scenario


class TestStructuredScenarioAssessment(unittest.TestCase):
    CASES = (
        ("pump_cavitation", 60, "FIT-02-FLW", "ALM-P02-HP"),
        ("compressor_overspeed", 70, "CMP-01-SPD", "ALM-C01-VB"),
        ("screen_differential_pressure", 70, "LDT-110-SCR", "ALM-SCR-110-DL"),
        ("wet_well_high_level", 80, "LIT-101-WWL", "ALM-WW-101-HH"),
    )

    def test_assessment_tracks_each_scenario_equipment_alarm_contributor_and_actual_values(self):
        outputs = []
        for scenario_id, elapsed, contributor, alarm in self.CASES:
            scenario = get_scenario(scenario_id)
            values = scenario.get_tag_values(elapsed, {})
            recorded_value = values[contributor]
            event = {
                "candidate": {"primary_tag": alarm},
                "primary_tag": alarm,
                "story": {"causal_label": scenario.name},
                "correlated": {
                    "equipment_id": scenario.target_equipment,
                    "correlated_deviations": [{"tag": contributor, "precedes_primary": True}],
                },
                "evidence": {"likely_contributor_tag": contributor, "confidence_score": 0.6},
            }
            facts = {
                "incident_context": {"equipment": scenario.target_equipment, "alarm_id": alarm, "alarm_state": {"active": True}},
                "supporting_readings": [{"tag": contributor, "value": recorded_value, "data_source": "synthetic"}],
                "context": {"topology": {"registry_dependencies": []}},
            }
            observations = [{"kind": "trend", "tag": contributor, "summary": f"Recorded {recorded_value}"}]
            structured = _structured_assessment(event, facts, {"evidence": observations, "relevant_sop": {"approved": False}})
            self.assertEqual(structured["problem"]["equipment"], scenario.target_equipment)
            self.assertEqual(structured["problem"]["alarm"], alarm)
            self.assertIn(str(recorded_value), structured["problem"]["observations"][0]["summary"])
            self.assertEqual(structured["cause"]["contributor_tag"], contributor)
            self.assertFalse(structured["cause"]["confirmed"])
            self.assertFalse(structured["solution"]["approved_instructions"])
            self.assertIn("No approved operating instructions", structured["solution"]["summary"])
            outputs.append(structured)
        self.assertEqual(len({output["problem"]["equipment"] for output in outputs}), 4)
        self.assertEqual(len({output["cause"]["contributor_tag"] for output in outputs}), 4)


if __name__ == "__main__":
    unittest.main()
