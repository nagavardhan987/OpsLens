"""Timestamp-faithful summaries of recorded process readings."""
from datetime import datetime, timezone
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def summarize_readings(readings: Iterable[Dict[str, Any]], reference_timestamp: Optional[str] = None,
                       max_important_changes: int = 5,
                       window_start: Optional[str] = None,
                       expected_tags: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Summarize numeric observations per tag; never interpolate missing samples.

    Conflicting values at an identical timestamp are retained in extrema/counts,
    but that timestamp is excluded from ordered first/last and delta calculations
    because SQLite provides no physical ordering within one instant.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in readings:
        if item.get("tag"):
            grouped.setdefault(str(item["tag"]), []).append(item)

    reference = _timestamp(reference_timestamp)
    start = _timestamp(window_start)
    summaries = []
    for tag in sorted(set(grouped) | set(expected_tags or [])):
        items = grouped.get(tag, [])
        numeric: List[Tuple[datetime, float, Dict[str, Any]]] = []
        invalid_count = 0
        non_numeric_count = 0
        for item in items:
            value = item.get("value")
            stamp = _timestamp(item.get("timestamp_utc") or item.get("timestamp"))
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                non_numeric_count += 1
                continue
            if not math.isfinite(float(value)) or stamp is None:
                invalid_count += 1
                continue
            numeric.append((stamp, float(value), item))
        numeric.sort(key=lambda row: (row[0], str(row[2].get("timestamp_utc") or row[2].get("timestamp"))))

        by_time: Dict[datetime, List[Tuple[float, Dict[str, Any]]]] = {}
        for stamp, value, item in numeric:
            by_time.setdefault(stamp, []).append((value, item))
        ordered = []
        ambiguous_timestamps = 0
        duplicate_records = 0
        for stamp, observations in sorted(by_time.items()):
            distinct = {}
            for value, item in observations:
                distinct.setdefault(value, item)
            duplicate_records += len(observations) - len(distinct)
            if len(distinct) != 1:
                ambiguous_timestamps += 1
                continue
            value, original = next(iter(distinct.items()))
            ordered.append((stamp, value, original))

        # Extrema reflect every valid recorded numeric value, including distinct
        # simultaneous observations; ties use the earliest timestamp.
        min_row = min(numeric, key=lambda row: (row[1], row[0])) if numeric else None
        max_row = max(numeric, key=lambda row: (row[1], -row[0].timestamp())) if numeric else None
        first = ordered[0] if ordered else None
        last = ordered[-1] if ordered else None
        absolute_change = last[1] - first[1] if first and last else None
        percentage_change = (absolute_change / first[1] * 100.0
                             if absolute_change is not None and first[1] != 0 else None)

        changes = []
        intervals = []
        for previous, current in zip(ordered, ordered[1:]):
            seconds = (current[0] - previous[0]).total_seconds()
            if seconds > 0:
                intervals.append(seconds)
            delta = current[1] - previous[1]
            if delta == 0:
                continue
            changes.append({
                "from_timestamp": previous[0].isoformat().replace("+00:00", "Z"),
                "timestamp": current[0].isoformat().replace("+00:00", "Z"),
                "previous_value": previous[1], "value": current[1],
                "absolute_change": delta,
                "percentage_change": delta / previous[1] * 100.0 if previous[1] != 0 else None,
                "elapsed_seconds": seconds,
                "chronology": "before_alarm" if reference is None or current[0] < reference else "at_alarm",
            })
        # Rank by absolute change to select a compact set, then restore time order.
        selected = sorted(sorted(changes, key=lambda item: abs(item["absolute_change"]), reverse=True)[:max_important_changes],
                          key=lambda item: item["timestamp"])

        gap_threshold = min(intervals) * 2 if intervals else None
        gap_intervals = [value for value in intervals if gap_threshold is not None and value > gap_threshold]
        timestamps = [row[0] for row in ordered]
        coverage_seconds = ((timestamps[-1] - timestamps[0]).total_seconds() if len(timestamps) > 1 else 0.0)
        leading_unobserved = max(0.0, (timestamps[0] - start).total_seconds()) if timestamps and start else None
        trailing_unobserved = max(0.0, (reference - timestamps[-1]).total_seconds()) if timestamps and reference else None
        summary = {
            "tag": tag,
            "equipment_id": next((item.get("equipment_id") for item in items if item.get("equipment_id")), None),
            "unit": next((item.get("unit") for item in items if item.get("unit")), ""),
            "reading_count": len(numeric),
            "unique_timestamp_count": len(by_time),
            "invalid_reading_count": invalid_count,
            "non_numeric_reading_count": non_numeric_count,
            "duplicate_records_ignored": duplicate_records,
            "ambiguous_timestamp_count": ambiguous_timestamps,
            "first_observed": ({"value": first[1], "timestamp": first[0].isoformat().replace("+00:00", "Z")} if first else None),
            "last_observed": ({"value": last[1], "timestamp": last[0].isoformat().replace("+00:00", "Z")} if last else None),
            "minimum": ({"value": min_row[1], "timestamp": min_row[0].isoformat().replace("+00:00", "Z")} if min_row else None),
            "maximum": ({"value": max_row[1], "timestamp": max_row[0].isoformat().replace("+00:00", "Z")} if max_row else None),
            "absolute_change": absolute_change,
            "percentage_change": percentage_change,
            "observed_coverage_seconds": coverage_seconds if ordered else None,
            "leading_unobserved_seconds": leading_unobserved,
            "trailing_unobserved_seconds": trailing_unobserved,
            "important_changes": selected,
            "change_count": len(changes),
            "gap_count": len(gap_intervals),
            "gap_intervals_seconds": gap_intervals,
            "gap_detection": "Intervals greater than twice the shortest observed interval; cadence-based indicator, not proof of missing samples." if intervals else "Insufficient intervals to assess gaps.",
            "missing_data": ("No readings were recorded for this relevant tag." if not items else
                             "No valid numeric readings recorded." if not numeric else
                             "Conflicting values share one or more timestamps; those timestamps are excluded from ordered trend calculations." if ambiguous_timestamps else
                             "Invalid numerical value(s) or timestamp(s) excluded from trend calculations." if invalid_count else None),
            "coverage_note": (
                f"Numeric readings span {coverage_seconds:g} seconds inside the requested window; "
                f"no numeric reading was recorded during the first {leading_unobserved:g} seconds."
                if leading_unobserved is not None and leading_unobserved > 0 else
                "No numeric readings are recorded in this window." if not numeric else None
            ),
            "source": "Derived only from recorded context readings; no interpolation.",
        }
        summaries.append(summary)
    return summaries
