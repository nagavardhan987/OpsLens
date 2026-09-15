"""
OpsLens - Scenario A: Valve Restriction Cascade

Simulates a physical cascade on Pump-02:
Discharge throttle valve pinches closed -> flow decreases -> motor current increases ->
discharge line pressure builds up -> high pressure alarm trips.
Unfolds over ~75 seconds.
"""

from typing import Dict, Any
from scenarios.base import BaseScenario


class ValveRestrictionScenario(BaseScenario):
    """
    State machine for Valve Restriction Cascade on Pump-02.
    """

    def __init__(self):
        super().__init__(
            scenario_id="valve_restriction_cascade",
            name="Pump-02 Valve Restriction Cascade",
            description=(
                "Throttling valve VLV-04 closes unexpectedly, causing downstream "
                "flow starvation, motor current surge, line overpressure, and high pressure alarm trip."
            ),
            duration_seconds=75.0,
            target_equipment="Pump-02",
            expected_correlations=[
                "VLV-04-POS",
                "FIT-02-FLW",
                "MOT-02-CUR",
                "PIT-02-PRS",
                "ALM-P02-HP",
            ],
            expected_non_correlations=[
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
        Compute dynamic progression across the cascade window:
        - t in [0, 10): nominal
        - t in [10, 28): VLV-04-POS drops 78.0% -> 43.0%
        - t in [18, 38): FIT-02-FLW drops 82.0 -> 56.0 L/min
        - t in [28, 48): MOT-02-CUR rises 7.8 -> 9.2 A
        - t in [36, 58): PIT-02-PRS rises 4.8 -> 6.9 bar
        - t >= 52: ALM-P02-HP trips True
        """
        overrides: Dict[str, Any] = {}
        t = elapsed_seconds

        # 1. Valve Position: nominal (~78.0%) -> 43.0%
        if t < 10.0:
            pass  # keep nominal
        elif 10.0 <= t < 28.0:
            p = (t - 10.0) / 18.0
            nom = nominal_values.get("VLV-04-POS", 78.0)
            overrides["VLV-04-POS"] = round(self.smooth_transition(nom, 43.0, p), 2)
        else:
            overrides["VLV-04-POS"] = 43.0

        # 2. Discharge Flow Rate: nominal (~82.0) -> 56.0 L/min
        if t < 18.0:
            pass
        elif 18.0 <= t < 38.0:
            p = (t - 18.0) / 20.0
            nom = nominal_values.get("FIT-02-FLW", 82.0)
            overrides["FIT-02-FLW"] = round(self.smooth_transition(nom, 56.0, p), 2)
        else:
            overrides["FIT-02-FLW"] = 56.0

        # 3. Motor Current: nominal (~7.8) -> 9.2 A
        if t < 28.0:
            pass
        elif 28.0 <= t < 48.0:
            p = (t - 28.0) / 20.0
            nom = nominal_values.get("MOT-02-CUR", 7.8)
            overrides["MOT-02-CUR"] = round(self.smooth_transition(nom, 9.2, p), 2)
        else:
            overrides["MOT-02-CUR"] = 9.2

        # 4. Discharge Line Pressure: nominal (~4.8) -> 6.9 bar
        if t < 36.0:
            pass
        elif 36.0 <= t < 58.0:
            p = (t - 36.0) / 22.0
            nom = nominal_values.get("PIT-02-PRS", 4.8)
            overrides["PIT-02-PRS"] = round(self.smooth_transition(nom, 6.9, p), 2)
        else:
            overrides["PIT-02-PRS"] = 6.9

        # 5. High Pressure Alarm: trips once pressure exceeds 6.5 bar
        current_prs = overrides.get("PIT-02-PRS", nominal_values.get("PIT-02-PRS", 4.8))
        if current_prs >= 6.5:
            overrides["ALM-P02-HP"] = True
        else:
            overrides["ALM-P02-HP"] = False

        return overrides
