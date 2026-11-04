"""
OpsLens - Scenario E: Tank Overflow / High Level

Simulates upstream buffer tank TNK-01 filling beyond safe capacity:
- Tank level rises past 88% trip threshold
- No topology path back to Pump-02 tags => isolates as tank-only event
- NO matching SOP exists in the library (tests SOP-not-found fallback path)
- Unfolds over ~65 seconds.
"""

from typing import Dict, Any
from scenarios.base import BaseScenario


class TankOverflowScenario(BaseScenario):
    """
    State machine for Tank-01 Overflow event.
    Single-tag breach with no correlated cascade.
    Exercises the 'no SOP match' path in the retrieval engine.
    """

    def __init__(self):
        super().__init__(
            scenario_id="tank_overflow",
            name="Tank-01 High Level / Overflow Risk",
            description=(
                "Upstream buffer tank TNK-01 level rises toward overflow threshold due to "
                "blocked outlet. No SOP match — exercises fallback guidance path."
            ),
            duration_seconds=65.0,
            target_equipment="Tank-01",
            expected_correlations=["TNK-01-LVL"],
            expected_non_correlations=[
                "VLV-04-POS", "FIT-02-FLW", "MOT-02-CUR", "PIT-02-PRS", "ALM-P02-HP",
                "CMP-01-SPD", "CMP-01-VIB", "CMP-01-CUR", "CMP-01-TMP", "ALM-C01-VB",
            ],
        )

    def get_tag_values(
        self,
        elapsed_seconds: float,
        nominal_values: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        t in [0, 10):  nominal (~60%)
        t in [10, 55): TNK-01-LVL rises 60% -> 92%
        t >= 55:       holds at 92% (above 88% trip)
        """
        overrides: Dict[str, Any] = {}
        t = elapsed_seconds

        if t < 10.0:
            pass
        elif 10.0 <= t < 55.0:
            p = (t - 10.0) / 45.0
            nom = nominal_values.get("TNK-01-LVL", 60.0)
            overrides["TNK-01-LVL"] = round(self.smooth_transition(nom, 92.0, p), 2)
        else:
            overrides["TNK-01-LVL"] = 92.0

        return overrides
