"""Synthesize compact alarm context from temporal evidence and event ordering."""
from typing import Any, Dict, List
from alarm_priority import AlarmPriorityInterpreter


class AlarmSynthesisEngine:
    def synthesize(self, candidate, story, telemetry: List[Dict[str, Any]], observations: List[str]) -> Dict[str, Any]:
        equipment = telemetry[0].get("equipment") if telemetry else "Unknown equipment"
        alarm_step = next((step for step in reversed(story.steps) if str(step.tag).startswith("ALM-")), None)
        alarm_id = alarm_step.tag if alarm_step else candidate.primary_tag
        signals = {}
        for item in telemetry:
            tag = item.get("tag")
            if not tag: continue
            signal = {"current": item.get("value"), "unit": item.get("unit")}
            if "baseline" in item:
                signal.update({"baseline": item["baseline"], "deviation": item.get("deviation"),
                               "deviation_percent": item.get("deviation_percent")})
            signals[tag] = signal
        changed_signals = [item for item in telemetry if item.get("deviation_percent") is not None
                           and abs(item["deviation_percent"]) >= 10]
        changed_signals.sort(key=lambda item: item.get("timestamp", ""))
        return {
            "alarm_id": alarm_id,
            "equipment": equipment,
            "condition": story.causal_label,
            "severity": candidate.alarm_severity or "not supplied",
            "priority_interpretation": AlarmPriorityInterpreter.interpret(
                candidate.alarm_severity, related_signal_count=len(changed_signals)
            ),
            "timestamp": candidate.trigger_timestamp,
            "signals": signals,
            "observations": observations,
            "preceding_events": observations[:],
            "multi_signal_correlation": len(observations) > 1,
            "correlated_signals": [item.get("tag") for item in changed_signals],
            "signal_change_order": [item.get("tag") for item in changed_signals],
            "event_sequence": [step.description for step in story.steps],
        }
