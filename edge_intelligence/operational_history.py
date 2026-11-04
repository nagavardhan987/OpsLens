"""Read models for durable alarm and shift-handover history."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def configured_shift_window(now: Optional[datetime] = None) -> Optional[dict]:
    """Resolve a shift window from explicit configuration; never assume a schedule."""
    start_text = (os.getenv("OPSLENS_SHIFT_START") or "").strip()
    end_text = (os.getenv("OPSLENS_SHIFT_END") or "").strip()
    name = (os.getenv("OPSLENS_SHIFT_NAME") or "Configured shift").strip()
    if not start_text or not end_text:
        return None
    try:
        start_hour, start_minute = _parse_clock(start_text)
        end_hour, end_minute = _parse_clock(end_text)
    except ValueError:
        logger.error("handover_shift_configuration_invalid start=%s end=%s", start_text, end_text)
        return None
    now = now or datetime.now().astimezone()
    start_today = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end_today = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    overnight = (start_hour, start_minute) >= (end_hour, end_minute)
    if overnight:
        if now >= start_today:
            start, end = start_today, end_today + timedelta(days=1)
        else:
            start = start_today - timedelta(days=1)
            end = end_today
    else:
        if now < start_today:
            start, end = start_today - timedelta(days=1), end_today - timedelta(days=1)
        elif now >= end_today:
            start, end = start_today, end_today
        else:
            start, end = start_today, end_today
    return {"name": name or "Configured shift", "date": start.date().isoformat(),
            "start": start.isoformat(), "end": end.isoformat(), "configured": True}


def _parse_clock(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value)
    if not match:
        raise ValueError("Shift time must use 24-hour HH:MM format.")
    return int(match.group(1)), int(match.group(2))


def generate_shift_narrative(summary: dict, llm_complete_chat=None, provider: Optional[str] = None) -> dict:
    """Summarize retrieved records; use a local model only, with deterministic fallback."""
    generated = _deterministic_shift_narrative(summary)
    if llm_complete_chat is None:
        try:
            from llm_provider import complete_chat, selected_provider
            provider = selected_provider()
            llm_complete_chat = complete_chat
        except Exception:
            provider = "none"
    # The operator has explicitly prohibited sending incident data to Groq.
    # Permit only local providers for this incident-derived summary.
    if provider not in ("ollama", "transformers", "inprocess") or llm_complete_chat is None:
        return {"text": generated, "source": "deterministic", "status": "available"}
    if provider == "ollama":
        host = urlparse(os.getenv("EDGE_LLM_URL", "http://localhost:11434")).hostname
        if host not in ("localhost", "127.0.0.1", "::1"):
            return {"text": generated, "source": "deterministic", "status": "available",
                    "notice": "AI summary unavailable; configured model endpoint is not local."}
    source_json = json.dumps(summary, ensure_ascii=False, default=str)
    prompt = ("Write a concise shift-handover narrative using only the supplied JSON records. "
              "Do not infer causes, invent events, readings, people, timestamps, maintenance, procedures, or status. "
              "State that absent fields are unavailable. Mention what the incoming operator should review first. "
              "Return plain text only. Records:\n" + source_json)
    try:
        text = str(llm_complete_chat(prompt, timeout=4.0)).strip()
        if not text or not _summary_is_grounded(text, source_json):
            raise ValueError("summary grounding validation failed")
        return {"text": text, "source": "AI-generated (local model)", "status": "available"}
    except Exception as exc:
        logger.warning("handover_summary_generation_failed provider=%s error_type=%s error=%s",
                       provider, type(exc).__name__, str(exc))
        return {"text": generated, "source": "deterministic", "status": "fallback",
                "notice": "AI summary unavailable; showing a record-based summary."}


def _summary_is_grounded(text: str, source_json: str) -> bool:
    # Reject new numeric values, timestamps, and equipment/alarm identifiers.
    source = source_json.casefold()
    for token in re.findall(r"\b(?:\d+(?:\.\d+)?%?|ALM-[A-Z0-9-]+|[A-Z]{2,5}-\d{2,}[A-Z0-9-]*)\b", text, re.I):
        if token.casefold() not in source:
            return False
    return True


def _deterministic_shift_narrative(summary: dict) -> str:
    alarms = summary.get("open_alarms") or []
    unacked = summary.get("unacknowledged_alarms") or []
    unresolved = summary.get("unresolved_incidents") or []
    events = summary.get("events_in_shift")
    actions = summary.get("actions_in_shift")
    lines = []
    lines.append(f"Recorded this shift: {len(events)} event(s)." if events is not None else
                 "Shift event count unavailable because shift timing is not configured.")
    lines.append(f"Open alarms: {len(alarms)} ({len(unacked)} unacknowledged)." )
    if alarms:
        labels = [f"{item.get('alarm_id', 'Alarm ID not recorded')} on {item.get('equipment', 'equipment not recorded')} [{item.get('status', 'status not recorded')}]" for item in alarms[:5]]
        lines.append("Still open: " + "; ".join(labels) + ("; additional alarms recorded." if len(alarms) > 5 else "."))
    resolved = [item for item in (summary.get("alarms_resolved_in_shift") or [])]
    acknowledged = [item for item in (summary.get("alarms_acknowledged_in_shift") or [])]
    lines.append(f"Acknowledged during shift: {len(acknowledged)}; resolved during shift: {len(resolved)}.")
    lines.append(f"Unresolved incidents carried forward: {len(unresolved)}.")
    if unresolved:
        lines.append("Review first: " + ", ".join(item.get("incident_id", "incident ID not recorded") for item in unresolved[:5]) + ".")
    attention = summary.get("equipment_needing_attention") or []
    if attention:
        lines.append("Equipment needing attention: " + ", ".join(attention) + ".")
    trends = summary.get("abnormal_sensor_readings", {}).get("items") or []
    if trends:
        tags = [item.get("possible_contributor_tag", "tag not recorded") for item in trends]
        lines.append("Recorded evidence associations to review (possible contributors, not confirmed causes): " + ", ".join(tags) + ".")
    else:
        lines.append("Abnormal sensor trend records: Unavailable.")
    if actions is None:
        lines.append("Operator actions during shift: Unavailable.")
    else:
        lines.append(f"Operator actions recorded during shift: {len(actions)}; pending-action tracking: Unavailable.")
    lines.append("Equipment status, maintenance, permits/LOTO, laboratory results, and chemical inventory: Unavailable unless noted in operator observations.")
    return " ".join(lines)


def list_alarm_history(db, filters: Optional[Dict[str, str]] = None) -> list[dict]:
    filters = {key: str(value).strip().lower() for key, value in (filters or {}).items() if value}
    records = db.get_all_individual_alarms()
    candidates = {item.event_id: item for item in db.get_candidate_events()}
    result = []
    for alarm in records:
        incident_id = alarm["incident_id"]
        candidate = candidates.get(incident_id)
        occurrences = db.get_alarm_occurrences(alarm["alarm_id"])
        if not occurrences:
            occurrences = [{
                "occurrence_id": None, "alarm_id": alarm["alarm_id"], "incident_id": incident_id,
                "occurred_at": alarm["first_seen_timestamp"], "value": alarm["value"],
                "lifecycle_state": alarm["lifecycle_state"], "data_source": "legacy aggregate",
                "data_quality": "PARTIAL",
            }]
            if alarm["last_seen_timestamp"] != alarm["first_seen_timestamp"]:
                occurrences.append({**occurrences[0], "occurrence_id": None,
                                    "occurred_at": alarm["last_seen_timestamp"], "value": alarm["value"]})
        transitions = db.get_alarm_transitions(alarm["alarm_id"])
        actions = [action.model_dump() for action in db.get_operator_actions(event_id=incident_id)]
        incident_status = db.get_event_status(incident_id)
        lifecycle = (transitions[-1]["state"].upper() if transitions else str(alarm["lifecycle_state"]).upper())
        if incident_status == "UNRESOLVED":
            status = "UNRESOLVED"
        elif incident_status == "RESOLVED":
            status = "RESOLVED"
        elif lifecycle in ("CLEARED", "RETURNED_TO_NORMAL"):
            status = "RETURNED_TO_NORMAL"
        elif lifecycle in ("ACKNOWLEDGED", "ACKNOWLEDGE") or alarm.get("acknowledged_timestamp"):
            status = "ACKNOWLEDGED"
        else:
            status = "ACTIVE"
        ack = next((transition for transition in reversed(transitions) if transition["state"].upper() == "ACKNOWLEDGED"), None)
        cleared = next((transition for transition in reversed(transitions) if transition["state"].upper() in ("CLEARED", "RETURNED_TO_NORMAL")), None)
        resolved = next((action for action in reversed(actions) if action["action_type"].upper() in ("RESOLVE", "RESOLVED")), None)
        story = db.get_event_stories(event_id=incident_id)
        description = story[0].causal_label if story else f"{alarm['tag']} alarm; description not separately recorded"
        source = occurrences[-1].get("data_source", "unknown")
        quality = occurrences[-1].get("data_quality", "UNKNOWN")
        record = {
            "alarm_record_id": alarm["alarm_id"], "alarm_id": alarm["tag"], "alarm_description": description,
            "equipment": alarm["equipment_id"], "process_area": "Not recorded",
            "severity": (candidate.alarm_severity if candidate and candidate.alarm_severity else "Not recorded"),
            "priority": (candidate.source_priority if candidate and candidate.source_priority else alarm.get("source_priority") or "Not recorded"),
            "first_triggered_at": alarm["first_seen_timestamp"], "latest_triggered_at": alarm["last_seen_timestamp"],
            "occurrences": occurrences, "occurrences_not_individually_retained": max(0, int(alarm.get("repeat_count") or 1) - len(occurrences)),
            "acknowledged_at": (ack or {}).get("timestamp") or alarm.get("acknowledged_timestamp"),
            "acknowledged_by": (ack or {}).get("operator"),
            "returned_to_normal_at": (cleared or {}).get("timestamp") or alarm.get("cleared_timestamp"),
            "resolved_at": (resolved or {}).get("timestamp"), "resolved_by": (resolved or {}).get("operator"),
            "repeat_count": max(1, int(alarm.get("repeat_count") or 1)), "incident_id": incident_id,
            "related_alarms": [row["tag"] for row in records if row["incident_id"] == incident_id and row["alarm_id"] != alarm["alarm_id"]],
            "operator_actions": actions, "transitions": transitions, "status": status,
            "data_source": source or "unknown", "data_quality": quality or "UNKNOWN",
        }
        search_blob = " ".join(str(record.get(key) or "") for key in ("alarm_id", "alarm_description", "equipment", "process_area", "severity", "priority", "incident_id", "acknowledged_by", "resolved_by")).lower()
        if filters.get("q") and filters["q"] not in search_blob:
            continue
        if filters.get("status") and filters["status"] not in ("all", "all alarms"):
            expected = filters["status"].replace(" ", "_").upper()
            if expected == "UNACKNOWLEDGED":
                if record["acknowledged_at"] or status not in ("ACTIVE", "ACKNOWLEDGED", "UNRESOLVED"):
                    continue
            elif expected == "ACTIVE":
                if status not in ("ACTIVE", "ACKNOWLEDGED", "UNRESOLVED"):
                    continue
            elif expected != status:
                continue
        checks = (("alarm_id", record["alarm_id"]), ("equipment", record["equipment"]),
                  ("process_area", record["process_area"]), ("severity", record["severity"]),
                  ("priority", record["priority"]), ("incident_id", record["incident_id"]))
        if any(filters.get(key) and filters[key] not in str(value).lower() for key, value in checks):
            continue
        if filters.get("operator") and filters["operator"] not in " ".join(str(a.get("operator") or "") for a in actions).lower():
            continue
        when = _parse_time(record["first_triggered_at"])
        start = _parse_time(filters.get("start")) if filters.get("start") else None
        end = _parse_time(filters.get("end")) if filters.get("end") else None
        if when and start and when < start:
            continue
        if when and end and when > end:
            continue
        result.append(record)
    result.sort(key=lambda item: item.get("latest_triggered_at") or "", reverse=True)
    return result


def _parse_time(value: Optional[str]):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def build_handover_summary(db, shift_start: Optional[str], shift_end: Optional[str]) -> dict:
    alarms = list_alarm_history(db)
    open_alarms = [alarm for alarm in alarms if alarm["status"] in ("ACTIVE", "ACKNOWLEDGED", "UNRESOLVED")]
    unacknowledged = [alarm for alarm in open_alarms if not alarm.get("acknowledged_at")]
    incident_ids = db.get_open_event_ids()
    incidents = [{"incident_id": event_id, "status": db.get_event_status(event_id)} for event_id in incident_ids]
    abnormal_readings = []
    for event_id in incident_ids:
        evidence = db.get_evidence(event_id=event_id)
        if evidence:
            abnormal_readings.append({
                "incident_id": event_id,
                "possible_contributor_tag": evidence[0].likely_contributor_tag,
                "supporting_deltas": [item.model_dump() for item in evidence[0].supporting_deltas],
                "interpretation": "Recorded evidence engine associations; not confirmation of physical cause.",
            })
    has_window = bool(shift_start and shift_end)
    events = db.get_events_in_window(shift_start, shift_end) if has_window else None
    actions = [action.model_dump() for action in db.get_actions_in_window(shift_start, shift_end)] if has_window else None
    event_story_records = []
    for event_id in events or []:
        for story in db.get_event_stories(event_id=event_id):
            event_story_records.append(story.model_dump())
    acknowledged, resolved = [], []
    equipment_attention = sorted({str(alarm.get("equipment") or "Equipment not recorded") for alarm in open_alarms})
    sensor_readings = []
    for equipment in equipment_attention:
        if equipment == "Equipment not recorded":
            continue
        try:
            readings = db.get_readings(equipment_id=equipment, limit=20, order_desc=True)
        except Exception:
            readings = []
        seen_tags = set()
        for reading in readings:
            if reading.tag in seen_tags:
                continue
            seen_tags.add(reading.tag)
            sensor_readings.append({"tag": reading.tag, "equipment": reading.equipment_id,
                                    "value": reading.value, "unit": reading.unit,
                                    "timestamp": reading.timestamp, "data_source": reading.data_source,
                                    "data_quality": reading.data_quality,
                                    "record_type": "live PLC" if "live" in str(reading.data_source).lower() else
                                                   "simulated" if "sim" in str(reading.data_source).lower() else "recorded"})
    if has_window:
        for alarm in alarms:
            for transition in alarm.get("transitions", []):
                ts = transition.get("timestamp")
                if not _in_window(ts, shift_start, shift_end):
                    continue
                state = str(transition.get("state", "")).upper()
                row = {"alarm_id": alarm.get("alarm_id"), "equipment": alarm.get("equipment"),
                       "timestamp": ts, "operator": transition.get("operator")}
                if state in ("ACKNOWLEDGED", "ACKNOWLEDGE"):
                    acknowledged.append(row)
                elif state in ("RESOLVED", "RESOLVE"):
                    resolved.append(row)
    not_recorded = {"status": "Unavailable", "items": [], "detail": "No corresponding record is stored in OpsLens."}
    return {
        "shift_start": shift_start, "shift_end": shift_end,
        "last_data_refresh": datetime.now().astimezone().isoformat(),
        "open_alarms": open_alarms, "unacknowledged_alarms": unacknowledged,
        "unresolved_incidents": incidents,
        "equipment_out_of_service": dict(not_recorded), "active_permits": dict(not_recorded),
        "loto_status": dict(not_recorded), "process_changes": dict(not_recorded),
        "abnormal_sensor_readings": {"status": "Recorded evidence available" if abnormal_readings else "Unavailable", "items": abnormal_readings,
                                     "detail": "No abnormal-reading evidence is stored for open incidents." if not abnormal_readings else None},
        "latest_sensor_readings": {"status": "Recorded" if sensor_readings else "Unavailable", "items": sensor_readings},
        "equipment_needing_attention": equipment_attention,
        "chemical_and_polymer_stock": dict(not_recorded), "pending_laboratory_results": dict(not_recorded),
        "pending_maintenance": dict(not_recorded), "outstanding_operator_actions": dict(not_recorded),
        "events_in_shift": events, "actions_in_shift": actions,
        "event_story_records": event_story_records if has_window else None,
        "alarms_acknowledged_in_shift": acknowledged if has_window else None,
        "alarms_resolved_in_shift": resolved if has_window else None,
        "summary_status": "Ready for operator review" if has_window else "Shift timing not configured",
    }


def _in_window(value: Optional[str], start: str, end: str) -> bool:
    try:
        timestamp = _parse_time(value)
        lower, upper = _parse_time(start), _parse_time(end)
        return timestamp is not None and lower is not None and upper is not None and lower <= timestamp <= upper
    except (TypeError, ValueError):
        return False
