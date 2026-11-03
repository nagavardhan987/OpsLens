"""Synthetic inlet-screen fouling / high differential-pressure scenario."""
from typing import Any, Dict

from scenarios.base import BaseScenario


class ScreenDifferentialPressureScenario(BaseScenario):
    def __init__(self):
        super().__init__(
            scenario_id="screen_differential_pressure",
            name="Inlet Works — Screen Differential Pressure High",
            description=(
                "SIMULATED screen-blockage signature: differential pressure rises, "
                "inlet flow trends lower, rake motor current rises and the screen alarm annunciates."
            ),
            duration_seconds=70.0,
            target_equipment="InletWorks-01",
            expected_correlations=["DPT-110-SCR", "ALM-SCR-110-DP", "FIT-110-IN", "SCR-110-RAKE-RUN", "SCR-110-MOT-CUR"],
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
        if t >= 14.0:
            progress = min(1.0, (t - 14.0) / 42.0)
            values["FIT-110-IN"] = round(self.smooth_transition(nominal_values.get("FIT-110-IN", 2050.0), 1780.0, progress), 2)
        if t >= 20.0:
            progress = min(1.0, (t - 20.0) / 35.0)
            values["SCR-110-MOT-CUR"] = round(self.smooth_transition(nominal_values.get("SCR-110-MOT-CUR", 7.5), 14.0, progress), 2)
        values["SCR-110-RAKE-RUN"] = t < 55.0
        differential_pressure = values.get("DPT-110-SCR", nominal_values.get("DPT-110-SCR", 1.0))
        values["ALM-SCR-110-DP"] = differential_pressure >= 4.0
        return values
