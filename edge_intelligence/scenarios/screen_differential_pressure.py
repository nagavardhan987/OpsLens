"""Synthetic inlet-screen fouling / high differential-pressure scenario."""
from typing import Any, Dict

from scenarios.base import BaseScenario


class ScreenDifferentialPressureScenario(BaseScenario):
    def __init__(self):
        super().__init__(
            scenario_id="screen_differential_pressure",
            name="Inlet Works — Screen Differential Pressure High",
            description=(
                "Synthetic screen-fouling signature: differential pressure rises "
                "across the coarse screen and its alarm input annunciates."
            ),
            duration_seconds=70.0,
            target_equipment="InletWorks-01",
            expected_correlations=["DPT-110-SCR", "ALM-SCR-110-DP", "FIT-110-IN"],
            expected_non_correlations=[
                "LIT-101-WWL", "AIT-201-DO", "AIT-201-NH4", "ALM-WW-101-HH",
            ],
        )

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        t = elapsed_seconds
        values: Dict[str, Any] = {}
        if t >= 8.0:
            initial = nominal_values.get("DPT-110-SCR", 1.0)
            progress = min(1.0, (t - 8.0) / 42.0)
            values["DPT-110-SCR"] = round(self.smooth_transition(initial, 4.8, progress), 2)
        differential_pressure = values.get("DPT-110-SCR", nominal_values.get("DPT-110-SCR", 1.0))
        values["ALM-SCR-110-DP"] = differential_pressure >= 4.0
        return values
