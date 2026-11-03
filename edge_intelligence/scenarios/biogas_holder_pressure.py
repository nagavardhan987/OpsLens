"""Simulated high biogas holder pressure and CHP trip sequence."""
from typing import Any, Dict
from scenarios.base import BaseScenario


class BiogasHolderPressureScenario(BaseScenario):
    def __init__(self):
        super().__init__("biogas_holder_pressure", "Biogas System — High Holder Pressure / CHP Trip", "SIMULATED CHP trip with holder pressure and fill trending upward; flare and gas-detector states are recorded separately.", 90.0, "BiogasSystem-01", ["CHP-601-RUN", "GAS-601-PRESS", "GAS-601-FILL", "FLR-601-RUN", "GAS-601-H2S", "GAS-601-FLOW", "ALM-GAS-601-HIGH"], ["DPT-110-SCR", "LIT-101-WWL"])

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        p = min(1.0, max(0.0, (elapsed_seconds - 10.0) / 65.0))
        pressure = self.smooth_transition(20.0, 39.0, p)
        return {"GAS-601-PRESS": round(pressure, 1), "GAS-601-FILL": round(self.smooth_transition(55.0, 94.0, p), 1),
                "CHP-601-RUN": elapsed_seconds < 18.0, "FLR-601-RUN": elapsed_seconds >= 30.0,
                "GAS-601-H2S": round(self.smooth_transition(2.0, 3.0, p), 1), "GAS-601-FLOW": round(self.smooth_transition(300.0, 180.0, p), 1),
                "ALM-GAS-601-HIGH": pressure >= 35.0}
