"""Low-cost contextualization of incoming telemetry before event reasoning."""
from collections import defaultdict, deque
from statistics import mean, pstdev
from typing import Any, Dict, Deque, List


class TimeSeriesProcessor:
    """Maintain bounded per-tag history and emit compact process observations."""
    def __init__(self, history_size: int = 120):
        self.history_size = history_size
        self._history: Dict[str, Deque[Dict[str, Any]]] = defaultdict(lambda: deque(maxlen=history_size))

    def process(self, reading) -> Dict[str, Any]:
        item = {"timestamp": reading.timestamp, "tag": reading.tag, "equipment": reading.equipment_id,
                "value": reading.value, "unit": reading.unit,
                "alarm_state": getattr(reading, "alarm_state", None)}
        history = self._history[reading.tag]
        numeric = isinstance(reading.value, (int, float)) and not isinstance(reading.value, bool)
        prior = [float(x["value"]) for x in history if isinstance(x["value"], (int, float)) and not isinstance(x["value"], bool)]
        history.append(item)
        result = {**item, "observation": "value received"}
        try:
            from tag_registry import TAG_REGISTRY
            entry = TAG_REGISTRY.get(reading.tag)
            threshold = entry.trip_threshold if entry else None
            low_alarm = bool(entry and any(word in (entry.short_label or "").lower() for word in ("reduction", "low")))
        except Exception:
            threshold, low_alarm = None, False
        result["threshold_exceeded"] = bool(numeric and threshold is not None and
                                           (float(reading.value) <= float(threshold) if low_alarm else float(reading.value) >= float(threshold)))
        if result["threshold_exceeded"]:
            result["observation"] = f"{reading.tag} crossed its configured threshold"
        if numeric:
            current = float(reading.value)
            baseline = mean(prior) if prior else current
            result.update({"baseline": baseline, "deviation": current - baseline,
                           "deviation_percent": ((current-baseline)/abs(baseline)*100) if baseline else None,
                           "trend": "increasing" if len(prior) and current > prior[-1] else "decreasing" if len(prior) and current < prior[-1] else "stable",
                           "rate_of_change": (current-prior[-1]) if prior else 0.0,
                           "change_point": bool(len(prior) >= 5 and abs(current-mean(prior[-5:])) > 3*pstdev(prior[-5:]))})
            if len(prior) >= 3 and result["deviation_percent"] is not None and abs(result["deviation_percent"]) >= 10:
                result["observation"] = f"{reading.tag} {result['trend']} {abs(result['deviation_percent']):.1f}% from recent baseline"
        return result

    def snapshot(self, equipment: str) -> List[Dict[str, Any]]:
        latest = [history[-1] for history in self._history.values() if history and history[-1]["equipment"] == equipment]
        return latest

    def observations(self, equipment: str) -> List[str]:
        out = []
        for tag, history in self._history.items():
            if history and history[-1]["equipment"] == equipment:
                value = history[-1]
                obs = value.get("observation")
                if obs and obs != "value received": out.append(obs)
        return out
