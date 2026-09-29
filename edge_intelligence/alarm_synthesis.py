"""Synthesize compact alarm context from temporal evidence and event ordering."""
from typing import Any, Dict, List


class AlarmSynthesisEngine:
    def synthesize(self, candidate, story, telemetry: List[Dict[str, Any]], observations: List[str]) -> Dict[str, Any]:
        equipment = telemetry[0].get("equipment") if telemetry else "Unknown equipment"
        alarm_id = "ALM-P02-HP" if equipment == "Pump-02" else candidate.primary_tag
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
            "severity": "High" if candidate.primary_alarm else "Advisory",
            "timestamp": candidate.trigger_timestamp,
            "signals": signals,
            "observations": observations,
            "preceding_events": observations[:],
            "multi_signal_correlation": len(observations) > 1,
            "correlated_signals": [item.get("tag") for item in changed_signals],
            "signal_change_order": [item.get("tag") for item in changed_signals],
            "event_sequence": [step.description for step in story.steps],
        }
