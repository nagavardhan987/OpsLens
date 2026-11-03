"""Synthetic RAS pump failure and rising sludge blanket demonstration."""
from typing import Any, Dict

from scenarios.base import BaseScenario


class RaspumpFailureScenario(BaseScenario):
    def __init__(self):
        super().__init__(
            scenario_id="ras_pump_failure",
            name="RAS Pump Failure — Sludge Blanket High",
            description=(
                "SIMULATED RAS pump P1 failure: pump status and current drop, total RAS flow falls, "
                "then clarifier sludge blanket depth rises and alarms. Correlation does not prove cause."
            ),
            duration_seconds=90.0,
            target_equipment="RASSystem-01",
            expected_correlations=["RAS-P1-RUN", "RAS-P1-CUR", "RAS-FLOW", "SLB-201-DEPTH", "ALM-RAS-P1-FAIL", "ALM-SLB-201-HIGH"],
            expected_non_correlations=["DPT-110-SCR", "ALM-SCR-110-DP", "ALM-P02-HP", "CMP-01-VIB"],
        )

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        t = elapsed_seconds
        flow_initial = nominal_values.get("RAS-FLOW", 770.0)
        current_initial = nominal_values.get("RAS-P1-CUR", 22.0)
        blanket_initial = nominal_values.get("SLB-201-DEPTH", 0.55)
        flow = flow_initial
        blanket = blanket_initial
        values: Dict[str, Any] = {"RAS-P1-RUN": t < 18.0, "ALM-RAS-P1-FAIL": t >= 18.0}
        if t >= 8.0:
            progress = min(1.0, (t - 8.0) / 32.0)
            flow = self.smooth_transition(flow_initial, 480.0, progress)
            values["RAS-FLOW"] = round(flow, 2)
        if t >= 18.0:
            values["RAS-P1-CUR"] = 0.0
        elif t >= 8.0:
            progress = min(1.0, (t - 8.0) / 10.0)
            values["RAS-P1-CUR"] = round(self.smooth_transition(current_initial, 0.0, progress), 2)
        if t >= 20.0:
            progress = min(1.0, (t - 20.0) / 65.0)
            blanket = self.smooth_transition(blanket_initial, 1.8, progress)
            values["SLB-201-DEPTH"] = round(blanket, 2)
        values["ALM-SLB-201-HIGH"] = blanket >= 1.5
        return values
