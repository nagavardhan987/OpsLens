"""
OpsLens - Scenario G: Pump Low Flow / Cavitation

Simulates early-stage pump cavitation on Pump-02:
- Flow (FIT-02-FLW) drops gradually below low-flow threshold
- Discharge pressure (PIT-02-PRS) becomes erratic then drops
- Valve (VLV-04-POS) is fully open — rules out valve throttle fault
- Motor current (MOT-02-CUR) drops slightly (reduced hydraulic load)
- NO high-pressure alarm (ALM-P02-HP remains false)

This signature mimics partial valve restriction but is differentiated by:
  VLV-04-POS = fully OPEN (not closed), MOT-02-CUR drops (not rises).
Low SOP match confidence — tests partial-match retrieval path.
Unfolds over ~60 seconds.
"""

from typing import Dict, Any
from scenarios.base import BaseScenario


class PumpCavitationScenario(BaseScenario):
    """
    State machine for Pump-02 Low-Flow Cavitation.
    """

    def __init__(self):
        super().__init__(
            scenario_id="pump_cavitation",
            name="Pump-02 Low Flow / Cavitation",
            description=(
                "Pump-02 enters cavitation regime. Flow drops while valve stays fully open. "
                "Signature differentiates from valve restriction via VLV-04-POS trajectory."
            ),
            duration_seconds=60.0,
            target_equipment="Pump-02",
            expected_correlations=["FIT-02-FLW", "PIT-02-PRS", "MOT-02-CUR"],
            expected_non_correlations=[
                "VLV-04-POS", "ALM-P02-HP",
                "CMP-01-SPD", "CMP-01-VIB", "CMP-01-CUR", "CMP-01-TMP",
                "ALM-C01-VB", "TNK-01-LVL",
            ],
        )

    def get_tag_values(
        self,
        elapsed_seconds: float,
        nominal_values: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        t in [0, 10):  nominal
        t in [10, 40): FIT-02-FLW drops 82 -> 48 L/min
        t in [12, 40): PIT-02-PRS drops 4.8 -> 3.1 bar (low-pressure cavitation)
        t in [14, 40): MOT-02-CUR drops 7.8 -> 7.2 A (reduced load)
        VLV-04-POS held OPEN at 83%  (opposite of valve restriction)
        ALM-P02-HP remains False
        """
        overrides: Dict[str, Any] = {}
        t = elapsed_seconds

        # Valve stays fully open — key differentiator
        overrides["VLV-04-POS"] = 83.0

        # Flow drops
        if t < 10.0:
            pass
        elif 10.0 <= t < 40.0:
            p = (t - 10.0) / 30.0
            nom = nominal_values.get("FIT-02-FLW", 82.0)
            overrides["FIT-02-FLW"] = round(self.smooth_transition(nom, 48.0, p), 2)
        else:
            overrides["FIT-02-FLW"] = 48.0

        # Pressure drops (cavitation)
        if t < 12.0:
            pass
        elif 12.0 <= t < 40.0:
            p = (t - 12.0) / 28.0
            nom = nominal_values.get("PIT-02-PRS", 4.8)
            overrides["PIT-02-PRS"] = round(self.smooth_transition(nom, 3.1, p), 2)
        else:
            overrides["PIT-02-PRS"] = 3.1

        # Motor current drops slightly
        if t < 14.0:
            pass
        elif 14.0 <= t < 40.0:
            p = (t - 14.0) / 26.0
            nom = nominal_values.get("MOT-02-CUR", 7.8)
            overrides["MOT-02-CUR"] = round(self.smooth_transition(nom, 7.2, p), 2)
        else:
            overrides["MOT-02-CUR"] = 7.2

        # High pressure alarm stays off
        overrides["ALM-P02-HP"] = False

        return overrides
