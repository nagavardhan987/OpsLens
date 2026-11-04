"""
OpsLens Intelligence: Event Story Engine
Reconstructs the chronological incident timeline from distributed process logs
and alarm annunciator states.
"""

from typing import Dict, Any, List
from backend.data.scenario_data import TIMELINE_EVENTS


class EventStoryEngine:
    """
    Constructs the chronological narrative of what occurred before and during the alarm.
    Serves as the visual centerpiece of OpsLens for immediate operator situational awareness.
    """

    @staticmethod
    def get_timeline(is_incident: bool) -> List[Dict[str, Any]]:
        if not is_incident:
            return []
        return TIMELINE_EVENTS

    @staticmethod
    def get_summary(is_incident: bool) -> Dict[str, Any]:
        if not is_incident:
            return {
                "has_story": False,
                "headline": "Normal Operation",
                "events": []
            }

        return {
            "has_story": True,
            "headline": "Chronological Incident Reconstruction",
            "start_time": "14:31",
            "alarm_time": "14:32",
            "total_events": len(TIMELINE_EVENTS),
            "summary_statement": (
                "Sequence: Valve deviation (14:31) preceded flow reduction, "
                "motor current surge, and discharge overpressure trip (14:32)."
            ),
            "events": TIMELINE_EVENTS
        }
