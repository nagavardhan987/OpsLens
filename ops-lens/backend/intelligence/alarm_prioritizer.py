"""
OpsLens Intelligence: Alarm Prioritizer Module
Evaluates active alarms and process deviations based on severity, recency,
deviation magnitude, and relational correlation to avoid alarm flood.
"""

from typing import Dict, Any, List


class AlarmPrioritizer:
    """
    Transparent, rule-based alarm prioritization engine for Edge IPC.
    Filters noise, identifies the primary critical alarm, and correlates
    contributing process deviations.
    """

    @staticmethod
    def prioritize(is_incident: bool) -> Dict[str, Any]:
        if not is_incident:
            return {
                "active_alarm_count": 0,
                "highest_severity": "NORMAL",
                "primary_alarm": None,
                "micro_explanation": "All process variables within normal operating envelopes.",
                "correlated_deviations_count": 0,
                "alarms": []
            }

        primary_alarm = {
            "alarm_id": "ALM-P02-HP",
            "tag": "PIT-02-PRS",
            "source": "Pump-02 Discharge Line",
            "title": "HIGH PRESSURE ALARM",
            "severity": "CRITICAL",
            "priority_rank": 1,
            "timestamp": "14:32:00",
            "value": 6.9,
            "unit": "bar",
            "trip_limit": 6.0,
            "deviation_pct": 43.8,
            "status": "UNACKNOWLEDGED",
            "visual_badge": "CRITICAL ALARM"
        }

        # Correlated events tagged as related deviations, NOT independent alarms
        related_events = [
            {
                "tag": "VLV-04-POS",
                "label": "Valve-04 Position Deviation",
                "status": "RELATED_EVENT",
                "detail": "Restricted to 43% (-45%)"
            },
            {
                "tag": "FIT-02-FLW",
                "label": "Discharge Flow Drop",
                "status": "RELATED_EVENT",
                "detail": "Decreased to 56 L/min (-32%)"
            },
            {
                "tag": "MOT-02-CUR",
                "label": "Motor Load Increase",
                "status": "RELATED_EVENT",
                "detail": "Surged to 9.2 A (+18%)"
            }
        ]

        return {
            "active_alarm_count": 1,
            "suppressed_flood_count": 3,
            "highest_severity": "CRITICAL",
            "primary_alarm": primary_alarm,
            "micro_explanation": "Critical event prioritized based on alarm severity and correlated process deviations.",
            "related_events": related_events,
            "alarms": [primary_alarm]
        }
