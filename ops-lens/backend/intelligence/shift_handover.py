"""
OpsLens Intelligence: Shift Handover Module
Compiles structured operational handover logs bridging shift transitions,
preventing undocumented tribal knowledge loss.
"""

from typing import Dict, Any, List
from backend.data.scenario_data import FIXED_OPERATOR


class ShiftHandoverEngine:
    """
    Generates standardized shift handover summaries combining machine state,
    incident context, likely contributor, and operator interventions.
    """

    @staticmethod
    def generate_summary(
        is_incident: bool,
        operator_actions: List[Dict[str, Any]],
        current_status: str = "Monitoring"
    ) -> Dict[str, Any]:
        if not is_incident:
            return {
                "unit": "Pump-02",
                "shift": "Shift 2",
                "operator": FIXED_OPERATOR,
                "incident": "None (Steady state operation)",
                "likely_contributor": "N/A",
                "operator_action": "Routine monitoring conducted",
                "actions_list": [a["action_name"] for a in operator_actions] if operator_actions else ["Routine inspection"],
                "current_status": "Normal Operating Envelope",
                "pending_issue": "None",
                "handover_timestamp": "14:35:00",
                "ready_for_handover": True
            }

        # Format operator action text based on logged actions
        if operator_actions:
            latest_action = operator_actions[-1]["action_name"]
            # e.g., if VERIFY_VALVE_04 was clicked -> "Valve-04 verified"
            action_text = latest_action
            if "VERIFY" in latest_action.upper() and "VALVE" in latest_action.upper():
                action_text = "Valve-04 verified"
            elif "REVIEW" in latest_action.upper():
                action_text = "Pump-02 operating status reviewed"
            elif "COMPLETE" in latest_action.upper():
                action_text = "Incident mitigation actions completed"
            elif "SOP" in latest_action.upper():
                action_text = "HP-P02 SOP reviewed & executed"
        else:
            action_text = "Pending operator verification"

        return {
            "unit": "Pump-02",
            "shift": "Shift 2",
            "operator": FIXED_OPERATOR,
            "incident": "High pressure detected at 14:32",
            "likely_contributor": "Valve-04 restriction",
            "operator_action": action_text,
            "actions_list": [a["action_name"] for a in operator_actions],
            "current_status": current_status,
            "pending_issue": "None",
            "handover_timestamp": "14:35:00",
            "ready_for_handover": True,
            "card_summary": {
                "header": "SHIFT HANDOVER – PUMP-02",
                "lines": [
                    {"label": "Incident", "value": "High pressure detected at 14:32"},
                    {"label": "Likely contributor", "value": "Valve-04 restriction"},
                    {"label": "Operator action", "value": action_text},
                    {"label": "Current status", "value": current_status},
                    {"label": "Pending issue", "value": "None"}
                ]
            }
        }
