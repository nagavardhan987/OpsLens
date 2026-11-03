"""Monitoring schedule and measurement-quality case; no equipment failure is simulated."""
from typing import Any, Dict
from scenarios.base import BaseScenario


class MonitoringDueScenario(BaseScenario):
    def __init__(self):
        super().__init__("monitoring_due", "Process Monitoring — Sampling / Calibration Due", "SIMULATED overdue sample and calibration record flags demonstrate monitoring completeness, not an equipment failure.", 60.0, "ProcessMonitoring-01", ["LAB-901-SAMPLE-DUE", "LAB-901-RESULT-PENDING", "LAB-901-CAL-DUE", "LAB-901-MEAS-QUALITY", "ALM-LAB-901-DUE"], ["DPT-110-SCR", "LIT-101-WWL"])

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        due = elapsed_seconds >= 8.0
        return {"LAB-901-SAMPLE-DUE": due, "LAB-901-RESULT-PENDING": elapsed_seconds >= 14.0,
                "LAB-901-CAL-DUE": elapsed_seconds >= 20.0, "LAB-901-MEAS-QUALITY": "REVIEW DUE" if elapsed_seconds >= 20.0 else "GOOD",
                "ALM-LAB-901-DUE": elapsed_seconds >= 20.0}
