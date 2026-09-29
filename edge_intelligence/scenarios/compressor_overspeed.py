"""
OpsLens - Scenario F: Compressor Overspeed Cascade

Simulates a runaway compressor on Compressor-01:
- Speed governor failure causes CMP-01-SPD to exceed trip limit
- Vibration (CMP-01-VIB) rises rapidly as imbalance develops
- Stator current (CMP-01-CUR) climbs toward overload threshold
- Bearing temperature (CMP-01-TMP) rises from friction heat
- High vibration alarm (ALM-C01-VB) trips

4-step compressor-side cascade, completely separate from Pump-02.
Unfolds over ~70 seconds.
"""

from typing import Dict, Any
from scenarios.base import BaseScenario


class CompressorOverspeedScenario(BaseScenario):
    """
    State machine for Compressor-01 Overspeed / Vibration cascade.
    """

    def __init__(self):
        super().__init__(
            scenario_id="compressor_overspeed",
            name="Compressor-01 Overspeed & Vibration",
            description=(
                "Speed governor fault allows CMP-01 to exceed 3300 RPM, triggering "
                "vibration surge, stator current climb, bearing heating, and vibration alarm trip."
            ),
            duration_seconds=70.0,
            target_equipment="Compressor-01",
            expected_correlations=[
                "CMP-01-SPD", "CMP-01-VIB", "CMP-01-CUR", "CMP-01-TMP", "ALM-C01-VB",
            ],
            expected_non_correlations=[
                "VLV-04-POS", "FIT-02-FLW", "MOT-02-CUR", "PIT-02-PRS",
                "ALM-P02-HP", "TNK-01-LVL",
            ],
        )

    def get_tag_values(
        self,
        elapsed_seconds: float,
        nominal_values: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        t in [0, 8):   nominal
        t in [8, 28):  CMP-01-SPD 2980 -> 3380 RPM (overspeed)
        t in [14, 34): CMP-01-VIB 1.8 -> 8.2 mm/s
        t in [20, 42): CMP-01-CUR 49.0 -> 66.0 A (overload)
        t in [24, 48): CMP-01-TMP 63.0 -> 88.0 °C
        t >= 44:       ALM-C01-VB trips True
        """
        overrides: Dict[str, Any] = {}
        t = elapsed_seconds

        # 1. Speed
        if t < 8.0:
            pass
        elif 8.0 <= t < 28.0:
            p = (t - 8.0) / 20.0
            nom = nominal_values.get("CMP-01-SPD", 2980.0)
            overrides["CMP-01-SPD"] = round(self.smooth_transition(nom, 3380.0, p), 1)
        else:
            overrides["CMP-01-SPD"] = 3380.0

        # 2. Vibration
        if t < 14.0:
            pass
        elif 14.0 <= t < 34.0:
            p = (t - 14.0) / 20.0
            nom = nominal_values.get("CMP-01-VIB", 1.8)
            overrides["CMP-01-VIB"] = round(self.smooth_transition(nom, 8.2, p), 2)
        else:
            overrides["CMP-01-VIB"] = 8.2

        # 3. Stator Current
        if t < 20.0:
            pass
        elif 20.0 <= t < 42.0:
            p = (t - 20.0) / 22.0
            nom = nominal_values.get("CMP-01-CUR", 49.0)
            overrides["CMP-01-CUR"] = round(self.smooth_transition(nom, 66.0, p), 1)
        else:
            overrides["CMP-01-CUR"] = 66.0

        # 4. Bearing Temperature
        if t < 24.0:
            pass
        elif 24.0 <= t < 48.0:
            p = (t - 24.0) / 24.0
            nom = nominal_values.get("CMP-01-TMP", 63.0)
            overrides["CMP-01-TMP"] = round(self.smooth_transition(nom, 88.0, p), 1)
        else:
            overrides["CMP-01-TMP"] = 88.0

        # 5. Vibration Alarm
        vib = overrides.get("CMP-01-VIB", nominal_values.get("CMP-01-VIB", 1.8))
        overrides["ALM-C01-VB"] = vib >= 7.0

        return overrides
