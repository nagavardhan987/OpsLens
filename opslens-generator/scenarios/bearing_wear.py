"""
OpsLens - Scenario B: Bearing Wear Degradation

Simulates mechanical bearing wear on Compressor-01:
Drive end bearing vibration steadily increases -> motor load current rises ->
bearing temperature climbs -> high vibration alarm trips.
Crucially, Pump-02 tags and Tank-01 are completely isolated and nominal.
"""

from typing import Dict, Any
from scenarios.base import BaseScenario


class BearingWearScenario(BaseScenario):
    """
    State machine for Bearing Wear on Compressor-01.
    Ground-truth requirement: Pump-02 tags must NOT correlate.
    """

    def __init__(self):
        super().__init__(
            scenario_id="bearing_wear",
            name="Compressor-01 Bearing Wear Degradation",
            description=(
                "Progressive mechanical fatigue on Compressor-01 drive-end bearing. "
                "Vibration rises steadily, driving stator current and bearing heat up, "
                "culminating in vibration trip. No valve involvement."
            ),
            duration_seconds=80.0,
            target_equipment="Compressor-01",
            expected_correlations=[
                "CMP-01-VIB",
                "CMP-01-CUR",
                "CMP-01-TMP",
                "ALM-C01-VB",
            ],
            expected_non_correlations=[
                "VLV-04-POS",
                "FIT-02-FLW",
                "MOT-02-CUR",
                "PIT-02-PRS",
                "ALM-P02-HP",
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
        - t in [0, 15): nominal
        - t in [15, 55): CMP-01-VIB climbs 2.0 -> 7.8 mm/s
        - t in [25, 65): CMP-01-CUR climbs 49.0 -> 58.5 A
        - t in [30, 70): CMP-01-TMP climbs 63.0 -> 86.5 °C
        - t >= 50: ALM-C01-VB trips True when VIB >= 7.0 mm/s
        """
        overrides: Dict[str, Any] = {}
        t = elapsed_seconds

        # 1. Bearing Vibration: nominal (~2.0 mm/s) -> 7.8 mm/s
        if t < 15.0:
            pass
        elif 15.0 <= t < 55.0:
            p = (t - 15.0) / 40.0
            nom = nominal_values.get("CMP-01-VIB", 2.0)
            overrides["CMP-01-VIB"] = round(self.smooth_transition(nom, 7.8, p), 2)
        else:
            overrides["CMP-01-VIB"] = 7.8

        # 2. Compressor Motor Current: nominal (~49.0 A) -> 58.5 A
        if t < 25.0:
            pass
        elif 25.0 <= t < 65.0:
            p = (t - 25.0) / 40.0
            nom = nominal_values.get("CMP-01-CUR", 49.0)
            overrides["CMP-01-CUR"] = round(self.smooth_transition(nom, 58.5, p), 2)
        else:
            overrides["CMP-01-CUR"] = 58.5

        # 3. Bearing Temperature: nominal (~63.0 °C) -> 86.5 °C
        if t < 30.0:
            pass
        elif 30.0 <= t < 70.0:
            p = (t - 30.0) / 40.0
            nom = nominal_values.get("CMP-01-TMP", 63.0)
            overrides["CMP-01-TMP"] = round(self.smooth_transition(nom, 86.5, p), 2)
        else:
            overrides["CMP-01-TMP"] = 86.5

        # 4. Vibration Alarm: trips when vibration >= 7.0 mm/s
        current_vib = overrides.get("CMP-01-VIB", nominal_values.get("CMP-01-VIB", 2.0))
        if current_vib >= 7.0:
            overrides["ALM-C01-VB"] = True
        else:
            overrides["ALM-C01-VB"] = False

        return overrides
