"""Simulated centrifuge solids-capture degradation and centrate quality event."""
from typing import Any, Dict
from scenarios.base import BaseScenario


class CentrifugeCaptureScenario(BaseScenario):
    def __init__(self):
        super().__init__("centrifuge_capture", "Dewatering Centrifuge — Low Solids Capture / High Centrate Ammonia", "SIMULATED capture decline with bowl speed, polymer dose, cake dryness, centrate and inlet ammonia context.", 90.0, "DewateringCentrifuge-01", ["SLD-701-BOWL-RPM", "SLD-701-POLYMER", "SLD-701-CAPTURE", "SLD-701-CAKE-DRY", "SLD-701-CENTRATE-NH4", "SLD-701-INLET-NH4", "ALM-SLD-701-CAPTURE"], ["DPT-110-SCR", "LIT-101-WWL"])

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        p = min(1.0, max(0.0, (elapsed_seconds - 8.0) / 68.0))
        capture = self.smooth_transition(94.0, 72.0, p)
        return {"SLD-701-BOWL-RPM": round(self.smooth_transition(3200.0, 3020.0, p)), "SLD-701-POLYMER": round(self.smooth_transition(40.0, 28.0, p), 1),
                "SLD-701-CAPTURE": round(capture, 1), "SLD-701-CAKE-DRY": round(self.smooth_transition(23.0, 18.0, p), 1),
                "SLD-701-CENTRATE-NH4": round(self.smooth_transition(35.0, 125.0, p), 1), "SLD-701-INLET-NH4": 38.0,
                "ALM-SLD-701-CAPTURE": capture < 80.0}
