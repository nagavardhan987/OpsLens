"""Synthetic aeration low dissolved oxygen with delayed ammonia rise."""
from typing import Any, Dict

from scenarios.base import BaseScenario


class LowDOAmmoniaRiseScenario(BaseScenario):
    def __init__(self):
        super().__init__(
            scenario_id="low_do_ammonia_rise",
            name="Aeration — Low DO / Ammonia Rise",
            description=(
                "Synthetic biological-treatment event: dissolved oxygen falls "
                "before ammonia concentration rises; both alarm inputs are recorded."
            ),
            duration_seconds=90.0,
            target_equipment="AerationBasin-01",
            expected_correlations=["AIT-201-DO", "AIT-201-NH4", "ALM-AER-201-DO", "ALM-AER-201-NH4"],
            expected_non_correlations=[
                "DPT-110-SCR", "LIT-101-WWL", "ALM-SCR-110-DP", "ALM-WW-101-HH",
            ],
        )

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        t = elapsed_seconds
        values: Dict[str, Any] = {}
        do = nominal_values.get("AIT-201-DO", 2.0)
        ammonia = nominal_values.get("AIT-201-NH4", 2.0)
        if t >= 8.0:
            do_progress = min(1.0, (t - 8.0) / 50.0)
            do = round(self.smooth_transition(do, 0.72, do_progress), 2)
            values["AIT-201-DO"] = do
        if t >= 20.0:
            ammonia_progress = min(1.0, (t - 20.0) / 50.0)
            ammonia = round(self.smooth_transition(ammonia, 9.0, ammonia_progress), 2)
            values["AIT-201-NH4"] = ammonia
        values["ALM-AER-201-DO"] = do <= 1.0
        values["ALM-AER-201-NH4"] = ammonia >= 8.0
        return values
