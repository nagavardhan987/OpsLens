"""Scenario 7: simulated tertiary-filter and UV disinfection degradation.

All values are speculative reference data from the supplied scenario document.
They are never live telemetry, operating limits, or an approved procedure.
"""
from typing import Any, Dict

from scenarios.base import BaseScenario


class FiltersUvDisinfectionFailureScenario(BaseScenario):
    def __init__(self):
        super().__init__(
            scenario_id="filters_uv_disinfection_failure",
            name="Scenario 7 — Filters Clog and UV Disinfection Fails",
            description=(
                "Simulated reference incident: BWP-1 trips after a shaft-seal failure; "
                "BWP-2 remains unavailable with its selector OFF; filter head loss and "
                "outlet turbidity rise, UV transmittance and lamp availability fall, "
                "and the UV low-dose alarm activates."
            ),
            duration_seconds=100.0,
            target_equipment="TertiaryTreatment-01",
            expected_correlations=[
                "BWP-1-TRIP", "BWP-2-SEL-OFF", "FLT-401-BW-HOURS", "FLT-401-HL",
                "FLT-401-TURB", "UV-501-UVT", "UV-501-LAMPS-ON", "UV-501-DOSE",
                "ALM-UV-501-DOSE-LOW",
            ],
            expected_non_correlations=[
                "LIT-101-WWL", "DPT-110-SCR", "AIT-201-DO", "AIT-201-NH4",
                "ALM-WW-101-HH", "ALM-SCR-110-DP",
            ],
        )

    def get_ground_truth(self) -> Dict[str, Any]:
        return {
            **super().get_ground_truth(),
            "source_status": "SIMULATED / REFERENCE ONLY",
            "approval_status": "not_applicable_simulated_scenario",
            "reference_notice": (
                "Scenario values are illustrative and require verification against plant design, "
                "equipment data, permit, and applicable regulations. No approved site procedure "
                "is supplied for tertiary filtration or UV disinfection."
            ),
            "missing_sops": [
                "SOP-TER-001", "SOP-DIS-001", "SOP-DIS-002", "SOP-CHM-001",
                "SOP-EFF-001", "SOP-LAB-002",
            ],
            "event_sequence": [
                "BWP-1 tripped following a simulated shaft-seal failure.",
                "BWP-2 did not start; its selector was recorded OFF in the scenario.",
                "The filters operated for 41 simulated hours without backwashing.",
                "Filter head loss rose to 2.9 m and outlet turbidity to 6.8 NTU.",
                "UV transmittance fell to 48% and 18 of 24 lamps remained in service.",
                "UV dose fell to 14 mJ/cm² and the simulated low-dose alarm activated.",
                "The reuse line was recorded closed and backup disinfection active in the scenario.",
            ],
        }

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        t = elapsed_seconds
        values: Dict[str, Any] = {
            "BWP-1-TRIP": "TRIPPED — simulated shaft-seal failure" if t >= 8.0 else "NORMAL",
            "BWP-2-SEL-OFF": "OFF" if t >= 8.0 else "NORMAL",
            "CHL-501-BACKUP-STATUS": "ACTIVE — simulated backup status" if t >= 92.0 else "NORMAL",
            "RLV-501-CLOSED": "CLOSED" if t >= 90.0 else "NORMAL",
            "ALM-UV-501-DOSE-LOW": False,
        }

        # The 100-second demo compresses the source scenario's 41-hour run.
        progress = self.smooth_transition(0.0, 1.0, (t - 8.0) / 82.0) if t >= 8 else 0.0
        values["FLT-401-BW-HOURS"] = round(41.0 * progress, 1)
        values["FLT-401-HL"] = round(0.9 + (2.9 - 0.9) * progress, 2)
        values["FLT-401-TURB"] = round(1.2 + (6.8 - 1.2) * progress, 2)
        values["UV-501-UVT"] = round(68.0 + (48.0 - 68.0) * progress, 1)
        values["UV-501-LAMPS-ON"] = 24 if t < 58.0 else 24 - round(6 * self.smooth_transition(0.0, 1.0, (t - 58.0) / 20.0))
        values["UV-501-DOSE"] = round(34.0 + (14.0 - 34.0) * progress, 1)
        values["UV-501-INTENSITY"] = round(15.0 + (6.2 - 15.0) * progress, 1)
        values["CHL-501-RESIDUAL"] = 1.2 if t >= 92.0 else 0.0
        values["LAB-501-COLIFORM"] = 1100.0 if t >= 98.0 else 0.0
        values["ALM-UV-501-DOSE-LOW"] = t >= 66.0
        return values
