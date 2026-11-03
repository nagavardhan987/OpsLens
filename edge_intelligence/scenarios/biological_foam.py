"""Simulated activated-sludge biological foam event (SOP-BIO-001 scope)."""
from typing import Any, Dict
from scenarios.base import BaseScenario


class BiologicalFoamScenario(BaseScenario):
    def __init__(self):
        super().__init__("biological_foam", "Aeration Tank — Biological Foam", "SIMULATED foam-depth increase with related process monitoring values; this is distinct from a low-DO/ammonia event.", 90.0, "AerationBasin-01", ["AER-201-FOAM-DEPTH", "AIT-201-DO", "AER-201-MLSS", "AER-201-SLUDGE-AGE", "AER-201-WAS-FLOW", "AER-201-EFF-TURB", "ALM-AER-201-FOAM"], ["DPT-110-SCR", "LIT-101-WWL"])

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        p = min(1.0, max(0.0, (elapsed_seconds - 8.0) / 65.0))
        foam = self.smooth_transition(3.0, 22.0, p)
        return {
            "AER-201-FOAM-DEPTH": round(foam, 1),
            "AIT-201-DO": round(self.smooth_transition(2.0, 1.6, p), 2),
            "AER-201-MLSS": round(self.smooth_transition(3000.0, 3300.0, p), 0),
            "AER-201-SLUDGE-AGE": round(self.smooth_transition(10.0, 16.0, p), 1),
            "AER-201-WAS-FLOW": round(self.smooth_transition(30.0, 24.0, p), 1),
            "AER-201-EFF-TURB": round(self.smooth_transition(2.0, 6.0, p), 1),
            "ALM-AER-201-FOAM": foam >= 15.0,
        }
