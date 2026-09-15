"""
OpsLens Intelligence: Operator Actions Logger
Maintains the audit log of operator decisions and human-in-the-loop interactions.
Ensures the AI acts strictly as an advisory copilot—never commanding equipment directly.
"""

from datetime import datetime
from typing import Dict, Any, List
from backend.data.scenario_data import FIXED_OPERATOR


class OperatorActionLogger:
    """
    Records operator acknowledgments and workflow actions.
    Updates the operational handover ledger.
    """

    def __init__(self):
        self.actions: List[Dict[str, Any]] = []

    def record_action(self, action_id: str, action_name: str, notes: str = "") -> Dict[str, Any]:
        entry = {
            "id": f"act-{len(self.actions) + 1}",
            "action_id": action_id,
            "action_name": action_name,
            "operator": FIXED_OPERATOR,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "logged_time_hmi": "14:33:15",
            "status": "RECORDED",
            "notes": notes or f"Action '{action_name}' executed by operator."
        }
        self.actions.append(entry)
        return entry

    def get_actions(self) -> List[Dict[str, Any]]:
        return self.actions

    def clear(self):
        self.actions = []
