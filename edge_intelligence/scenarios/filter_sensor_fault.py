"""Synthetic Filter-01 instrumentation fault: disagreeing and stale readings."""
from typing import Any, Dict

from scenarios.base import BaseScenario


class FilterSensorFaultScenario(BaseScenario):
    def __init__(self):
        super().__init__(
            scenario_id="filter_sensor_fault",
            name="Filter-01 — Sensor Fault",
            description=(
                "SIMULATED instrumentation anomaly: a primary filter turbidity reading diverges from its redundant sensor, "
                "then reports poor quality and stale/disconnected communication. No physical fault is confirmed."
            ),
            duration_seconds=48.0,
            target_equipment="Filter-01",
            expected_correlations=["FLT-401-PRI-NTU", "FLT-401-RED-NTU", "FLT-401-PRI-QUALITY", "FLT-401-PRI-COMMS", "ALM-FLT-401-SENSOR"],
            expected_non_correlations=["DPT-110-SCR", "ALM-SCR-110-DP", "ALM-P02-HP", "ALM-C01-VB"],
        )

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        t = elapsed_seconds
        primary = nominal_values.get("FLT-401-PRI-NTU", 1.2)
        if t >= 8.0:
            primary = 8.6
        return {
            "FLT-401-PRI-NTU": primary,
            "FLT-401-RED-NTU": nominal_values.get("FLT-401-RED-NTU", 1.2),
            "FLT-401-PRI-QUALITY": "POOR" if t >= 18.0 else "GOOD",
            "FLT-401-PRI-COMMS": "DISCONNECTED" if t >= 24.0 else "CONNECTED",
            "ALM-FLT-401-SENSOR": t >= 8.0,
        }

    def get_reading_metadata(self, tag: str, elapsed_seconds: float) -> Dict[str, Any]:
        if tag != "FLT-401-PRI-NTU" or elapsed_seconds < 24.0:
            return {}
        # Keep receipt time at the current simulated instant while the reported
        # sample timestamp is stale, as a real historian would distinguish them.
        return {"stale_by_seconds": 90.0, "data_quality": "STALE", "connection_status": "disconnected"}
