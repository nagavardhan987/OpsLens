"""
OpsLens - Scenario C: Mechanical Seal Leak

Simulates mechanical pump seal rupture on Pump-02:
Discharge fluid escapes past compromised seal faces -> discharge pressure drops
AND discharge flow drops simultaneously -> motor electrical load decreases slightly.
Critically, VLV-04-POS remains unchanged at nominal, differentiating this signature
from a valve throttling event.
"""

from typing import Dict, Any
from scenarios.base import BaseScenario


class SealLeakScenario(BaseScenario):
    """
    State machine for Mechanical Seal Rupture on Pump-02.
    Different signature than Valve Restriction: Flow down AND Pressure down together.
    """

    def __init__(self):
        super().__init__(
            scenario_id="seal_leak",
            name="Pump-02 Mechanical Seal Leak",
            description=(
                "Seal face degradation causes fluid loss. Discharge flow and pressure drop "
                "in tandem, while throttle valve position remains completely nominal."
            ),
            duration_seconds=60.0,
            target_equipment="Pump-02",
            expected_correlations=[
                "FIT-02-FLW",
                "PIT-02-PRS",
                "MOT-02-CUR",
            ],
            expected_non_correlations=[
                "VLV-04-POS",
                "ALM-P02-HP",
                "CMP-01-SPD",
                "CMP-01-VIB",
                "CMP-01-CUR",
                "CMP-01-TMP",
                "ALM-C01-VB",
                "TNK-01-LVL",
            ],
        )

    def get_tag_values(
        self,
        elapsed_seconds: float,
        nominal_values: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Dynamic progression:
        - t in [0, 12): nominal
        - t in [12, 38): PIT-02-PRS drops 4.8 -> 2.1 bar
        - t in [12, 38): FIT-02-FLW drops 82.0 -> 45.0 L/min
        - t in [16, 42): MOT-02-CUR drops 7.8 -> 7.1 A (reduced head load)
        - VLV-04-POS strictly nominal (no override)
        - ALM-P02-HP remains False (low pressure, not high)
        """
        overrides: Dict[str, Any] = {}
        t = elapsed_seconds

        # 1. Flow Rate: nominal (~82.0 L/min) -> 45.0 L/min (drops below 50 L/min low threshold)
        if t < 12.0:
            pass
        elif 12.0 <= t < 38.0:
            p = (t - 12.0) / 26.0
            nom = nominal_values.get("FIT-02-FLW", 82.0)
            overrides["FIT-02-FLW"] = round(self.smooth_transition(nom, 45.0, p), 2)
        else:
            overrides["FIT-02-FLW"] = 45.0

        # 2. Discharge Line Pressure: nominal (~4.8 bar) -> 2.1 bar
        if t < 12.0:
            pass
        elif 12.0 <= t < 38.0:
            p = (t - 12.0) / 26.0
            nom = nominal_values.get("PIT-02-PRS", 4.8)
            overrides["PIT-02-PRS"] = round(self.smooth_transition(nom, 2.1, p), 2)
        else:
            overrides["PIT-02-PRS"] = 2.1

        # 3. Motor Current: nominal (~7.8 A) -> 7.1 A (modest load drop)
        if t < 16.0:
            pass
        elif 16.0 <= t < 42.0:
            p = (t - 16.0) / 26.0
            nom = nominal_values.get("MOT-02-CUR", 7.8)
            overrides["MOT-02-CUR"] = round(self.smooth_transition(nom, 7.1, p), 2)
        else:
            overrides["MOT-02-CUR"] = 7.1

        # ALM-P02-HP remains strictly False
        overrides["ALM-P02-HP"] = False

        return overrides
