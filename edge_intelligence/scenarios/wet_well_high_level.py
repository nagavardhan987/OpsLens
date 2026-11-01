"""Synthetic lift-station low-discharge / wet-well high-high scenario.

Values are illustrative for the demo reference plant, not operating guidance.
"""
from typing import Any, Dict

from scenarios.base import BaseScenario


class WetWellHighLevelScenario(BaseScenario):
    def __init__(self):
        super().__init__(
            scenario_id="wet_well_high_level",
            name="Lift Station — Wet-Well High-High Level",
            description=(
                "Synthetic lift-station event: discharge flow and pressure fall, "
                "wet-well level rises, and the high-high level input annunciates."
            ),
            duration_seconds=80.0,
            target_equipment="LiftStation-01",
            expected_correlations=[
                "FIT-101-DIS", "PIT-101-DIS", "MOT-101-CUR", "LIT-101-WWL", "ALM-WW-101-HH",
            ],
            expected_non_correlations=[
                "DPT-110-SCR", "AIT-201-DO", "AIT-201-NH4", "ALM-SCR-110-DP",
            ],
        )

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        t = elapsed_seconds
        values: Dict[str, Any] = {}
        # Illustrative 50 MLD plant averages roughly 2,083 m³/h. A simulated
        # loss of lift discharge is represented by about 950 m³/h at plateau.
        schedules = (
            ("FIT-101-DIS", 8.0, 42.0, 950.0, 2025.0),
            ("PIT-101-DIS", 8.0, 40.0, 1.25, 2.4),
            ("MOT-101-CUR", 12.0, 42.0, 66.0, 92.5),
            ("LIT-101-WWL", 10.0, 50.0, 91.0, 47.5),
        )
        for tag, start, end, target, nominal in schedules:
            if t < start:
                continue
            initial = nominal_values.get(tag, nominal)
            p = min(1.0, (t - start) / (end - start))
            values[tag] = round(self.smooth_transition(initial, target, p), 2)

        level = values.get("LIT-101-WWL", nominal_values.get("LIT-101-WWL", 47.5))
        values["ALM-WW-101-HH"] = level >= 85.0
        return values
