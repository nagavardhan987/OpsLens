"""
OpsLens - Scenario D: Sensor Fault / False Positive Spike

Simulates an isolated instrumentation failure (pressure transmitter glitch):
Discharge pressure PIT-02-PRS spikes sharply with zero physical changes in the process:
flow, motor current, valve position, and compressor tags remain in nominal baseline noise.
Designed to test that downstream correlation engines reject false positives.
"""

from typing import Dict, Any
from scenarios.base import BaseScenario


class SensorFaultScenario(BaseScenario):
    """
    State machine for Sensor Fault / False Positive on PIT-02-PRS.
    A single tag spikes with zero physical support on topologically linked tags.
    """

    def __init__(self):
        super().__init__(
            scenario_id="sensor_fault",
            name="PIT-02-PRS Sensor Fault / False Positive",
            description=(
                "Transmitter electronics glitch causing a transient spike on PIT-02-PRS. "
                "No physical change in flow, valve position, or pump motor current. "
                "The correlation pipeline must NOT construct an event story."
            ),
            duration_seconds=40.0,
            target_equipment="Pump-02",
            expected_correlations=[
                "PIT-02-PRS",  # Only this tag exhibits deviation
            ],
            expected_non_correlations=[
                "VLV-04-POS",
                "FIT-02-FLW",
                "MOT-02-CUR",
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
        - t in [0, 10): nominal (~4.8 bar)
        - t in [10, 24): PIT-02-PRS spikes to 7.35 bar
        - t in [24, 40]: PIT-02-PRS recovers back to nominal
        - ALL other tags (FIT-02-FLW, MOT-02-CUR, VLV-04-POS, ALM-P02-HP) are strictly nominal.
        """
        overrides: Dict[str, Any] = {}
        t = elapsed_seconds

        nom_prs = nominal_values.get("PIT-02-PRS", 4.8)
        spike_val = 7.35

        if t < 10.0:
            pass  # nominal
        elif 10.0 <= t < 14.0:
            p = (t - 10.0) / 4.0
            overrides["PIT-02-PRS"] = round(self.smooth_transition(nom_prs, spike_val, p), 2)
        elif 14.0 <= t < 22.0:
            overrides["PIT-02-PRS"] = spike_val
        elif 22.0 <= t < 26.0:
            p = (t - 22.0) / 4.0
            overrides["PIT-02-PRS"] = round(self.smooth_transition(spike_val, nom_prs, p), 2)
        else:
            pass  # back to nominal

        # Crucially: Alarm does not fire or remains nominal False
        overrides["ALM-P02-HP"] = False

        return overrides
