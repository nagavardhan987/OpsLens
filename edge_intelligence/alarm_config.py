"""
OpsLens - Alarm configuration derived from the plant SOP manual (SOP-MAN-000).

This module is deterministic. It never writes to a PLC and never invents a
limit: every number comes from ``config/alarm_reference.json``, which records
the source page for each value.

It provides four things:

1. ``classify_tag`` - separates *configured alarm inputs* (e.g. ALM-WW-101-HH)
   from *equipment status* tags (e.g. P101-RUN) and *process measurements*
   (e.g. LIT-101-WWL). Only alarm inputs become alarm records; a running pump
   or a drifting analog value is evidence, not an alarm.
2. ``limit_context`` - compares a measured value against the manual's normal
   range and alarm/escalation limits and returns the margin to each limit,
   with a page citation. Calculations happen here, not in an LLM.
3. ``priority_for`` - looks up the P1/P2/P3 acknowledgement convention.
4. ``config_conflicts`` - lists every difference between the manual and the
   OpsLens tag registry so neither source is silently overwritten.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("opslens.alarm_config")

CONFIG_PATH = Path(os.environ.get(
    "OPSLENS_ALARM_REFERENCE",
    str(Path(__file__).resolve().parent / "config" / "alarm_reference.json"),
))

# Discrete tags that represent a fault/trip annunciation even though they do
# not use the ALM- prefix. A running/selector status is NOT listed here.
FAULT_TAG_PATTERN = re.compile(r"(^|-)(FAULT|TRIP)$", re.IGNORECASE)
STATUS_TAG_PATTERN = re.compile(r"(^|-)(RUN|RUNNING|SEL-OFF|STATUS|CLOSED|QUALITY|COMMS)$", re.IGNORECASE)

APPLIED_MAPPINGS = {"direct", "assumed"}


@lru_cache(maxsize=1)
def load_reference() -> Dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Alarm reference file not found at %s", CONFIG_PATH)
        return {"definitions": [], "priority_convention": {"levels": []}}
    except (OSError, ValueError) as exc:
        logger.error("Alarm reference file unreadable (%s)", type(exc).__name__)
        return {"definitions": [], "priority_convention": {"levels": []}}


def reload_reference() -> Dict[str, Any]:
    load_reference.cache_clear()
    return load_reference()


def definitions() -> List[Dict[str, Any]]:
    return list(load_reference().get("definitions") or [])


def definition_for_tag(tag: str) -> Optional[Dict[str, Any]]:
    """Return the manual definition mapped to a measurement or alarm tag."""
    if not tag:
        return None
    for item in definitions():
        if tag in measurement_tags(item) or tag in alarm_tags(item):
            return item
    return None


def measurement_tags(definition: Dict[str, Any]) -> List[str]:
    mapping = definition.get("opslens_mapping") or {}
    tags = list(mapping.get("tags") or [])
    if mapping.get("tag") and mapping["tag"] not in tags:
        tags.insert(0, mapping["tag"])
    return tags


def alarm_tags(definition: Dict[str, Any]) -> List[str]:
    mapping = definition.get("opslens_mapping") or {}
    tags = list(mapping.get("alarm_tags") or [])
    if mapping.get("alarm_tag") and mapping["alarm_tag"] not in tags:
        tags.insert(0, mapping["alarm_tag"])
    return tags


def classify_tag(tag: str, data_type: Optional[str] = None) -> str:
    """Return 'alarm', 'status' or 'measurement'.

    - ALM-* tags and *-FAULT / *-TRIP discrete tags are alarm inputs.
    - *-RUN, selector, quality and other discrete states are equipment status.
    - Everything else is a process measurement.
    """
    name = str(tag or "").strip()
    upper = name.upper()
    if upper.startswith("ALM-"):
        return "alarm"
    if FAULT_TAG_PATTERN.search(upper):
        return "alarm"
    if STATUS_TAG_PATTERN.search(upper):
        return "status"
    if data_type in ("bool", "string"):
        return "status"
    return "measurement"


def is_alarm_tag(tag: str, data_type: Optional[str] = None) -> bool:
    return classify_tag(tag, data_type) == "alarm"


def status_normal_value(tag: str) -> Optional[bool]:
    """Normal state of a discrete equipment-status tag (OpsLens demo config,
    not from the SOP manual). None means 'not configured' -> no evidence."""
    try:
        import incident_catalog
        status = incident_catalog.plant_statuses().get(tag)
        if status is not None:
            return status.normal if status.kind == "status" else None
    except Exception:
        pass
    states = load_reference().get("status_normal_states") or {}
    value = states.get(tag)
    return value if isinstance(value, bool) else None


def priority_levels() -> Dict[str, Dict[str, Any]]:
    levels = (load_reference().get("priority_convention") or {}).get("levels") or []
    return {str(level.get("priority")): level for level in levels}


def priority_for(priority: Optional[str]) -> Optional[Dict[str, Any]]:
    if not priority:
        return None
    match = re.search(r"\bP[123]\b", str(priority).upper())
    return priority_levels().get(match.group(0)) if match else None


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float) -> float:
    return round(value, 3)


def limit_context(tag: str, value: Any, *, data_quality: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Compare a value with the manual's limits for that tag.

    Returns None when the manual has no definition for the tag. When the
    mapping is a unit mismatch or a conflict, the definition is returned for
    reference but no comparison is made.
    """
    definition = definition_for_tag(tag)
    if definition is None:
        return None
    mapping = definition.get("opslens_mapping") or {}
    source = load_reference().get("source_document") or {}
    base = {
        "tag": tag,
        "definition_id": definition.get("id"),
        "parameter": definition.get("parameter"),
        "unit": definition.get("unit"),
        "sop_id": definition.get("sop_id"),
        "source_document": source.get("document_id"),
        "source_page": definition.get("source_page"),
        "document_status": source.get("approval_status"),
        "mapping": mapping.get("mapping"),
        "mapping_note": mapping.get("note"),
        "normal_text": (definition.get("normal") or {}).get("text"),
        "calculated_by": "deterministic_backend",
    }
    if tag not in measurement_tags(definition):
        # Alarm inputs share the definition but are discrete; no numeric check.
        base.update({"applied": False, "reason": "Discrete alarm input; compare the related measurement instead."})
        return base
    if mapping.get("mapping") not in APPLIED_MAPPINGS:
        base.update({"applied": False,
                     "reason": "Manual limit not applied: " + (mapping.get("note") or "mapping not confirmed.")})
        return base

    numeric = _to_float(value)
    if numeric is None:
        base.update({"applied": False, "value": value, "reason": "Reading missing or not numeric."})
        return base
    if str(data_quality or "").upper() in ("STALE", "INVALID"):
        base.update({"applied": False, "value": numeric,
                     "reason": f"Reading quality is {str(data_quality).upper()}; limits not evaluated."})
        return base

    normal = definition.get("normal") or {}
    low, high = _to_float(normal.get("low")), _to_float(normal.get("high"))
    if low is not None and numeric < low:
        normal_state = "below_normal"
    elif high is not None and numeric > high:
        normal_state = "above_normal"
    else:
        normal_state = "within_normal"

    comparisons = []
    exceeded = []
    next_limit = None
    for limit in definition.get("limits") or []:
        limit_value = _to_float(limit.get("value"))
        if limit_value is None:
            continue
        direction = limit.get("direction")
        if direction == "high":
            is_exceeded = numeric >= limit_value
            margin = limit_value - numeric
        else:
            is_exceeded = numeric <= limit_value
            margin = numeric - limit_value
        row = {
            "name": limit.get("name"),
            "direction": direction,
            "limit": limit_value,
            "exceeded": is_exceeded,
            "margin": _round(margin),
            "margin_text": (
                f"{abs(_round(margin))} {definition.get('unit')} beyond limit" if is_exceeded and margin != 0
                else ("at limit" if margin == 0 else f"{_round(margin)} {definition.get('unit')} to limit")
            ),
            "action": limit.get("action"),
            "priority": limit.get("priority"),
            "source_text": limit.get("text"),
            "source_page": limit.get("source_page") or definition.get("source_page"),
            "sop_id": limit.get("sop_id") or definition.get("sop_id"),
        }
        comparisons.append(row)
        if is_exceeded:
            exceeded.append(row)
        elif next_limit is None or row["margin"] < next_limit["margin"]:
            next_limit = row

    highest = exceeded[-1] if exceeded else None
    if exceeded:
        # The most severe exceeded limit is the furthest one in its direction.
        highest = max(exceeded, key=lambda r: r["limit"] if r["direction"] == "high" else -r["limit"])
    # "P1 (conditional)" limits (e.g. gas holder 38 mbar: P1 only if the flare
    # is not burning or the relief valve is venting) are reported separately;
    # OpsLens cannot verify the condition from telemetry alone.
    escalation = next((r for r in exceeded if str(r.get("priority") or "").strip() == "P1"), None)
    conditional = next((r for r in exceeded if "conditional" in str(r.get("priority") or "").lower()), None)
    base.update({
        "applied": True,
        "value": numeric,
        "normal_state": normal_state,
        "comparisons": comparisons,
        "exceeded_limits": [r["name"] for r in exceeded],
        "highest_exceeded": highest,
        "next_limit": next_limit,
        "p1_escalation_reached": escalation is not None,
        "p1_conditional_reached": conditional is not None,
        "p1_condition_text": conditional.get("action") if conditional else None,
        "summary": _summary(definition, numeric, normal_state, highest, next_limit),
    })
    return base


def _summary(definition, value, normal_state, highest, next_limit) -> str:
    unit = definition.get("unit") or ""
    parts = [f"{definition.get('parameter')} {value:g} {unit}".strip()]
    if highest:
        parts.append(f"has reached the {highest['name']} limit of {highest['limit']:g} {unit} "
                     f"({highest.get('sop_id') or definition.get('sop_id')} p.{highest['source_page']})")
    elif normal_state != "within_normal":
        parts.append(f"is outside the normal range {(definition.get('normal') or {}).get('text')} "
                     f"but below the first alarm limit")
    else:
        parts.append(f"is within the normal range {(definition.get('normal') or {}).get('text')}")
    sentence = " ".join(parts[:2])
    if next_limit:
        sentence += (f"; next limit {next_limit['name']} {next_limit['limit']:g} {unit} "
                     f"is {abs(next_limit['margin']):g} {unit} away")
    return sentence + "."


def config_conflicts() -> List[Dict[str, Any]]:
    """Compare the manual with the OpsLens tag registry. Never modifies either."""
    from tag_registry import TAG_REGISTRY

    conflicts: List[Dict[str, Any]] = []
    for definition in definitions():
        mapping = definition.get("opslens_mapping") or {}
        for tag in measurement_tags(definition):
            entry = TAG_REGISTRY.get(tag)
            if entry is None:
                conflicts.append({"tag": tag, "definition_id": definition.get("id"), "field": "tag",
                                  "manual": "mapped", "opslens": "tag missing from registry",
                                  "source_page": definition.get("source_page")})
                continue
            normal = definition.get("normal") or {}
            rows = []
            if entry.unit and definition.get("unit") and entry.unit.replace(" ", "") != str(definition.get("unit")).replace(" ", ""):
                rows.append(("unit", definition.get("unit"), entry.unit))
            if normal.get("low") is not None and _to_float(normal.get("low")) != _to_float(entry.baseline_min):
                rows.append(("normal_low", normal.get("low"), entry.baseline_min))
            if normal.get("high") is not None and _to_float(normal.get("high")) != _to_float(entry.baseline_max):
                rows.append(("normal_high", normal.get("high"), entry.baseline_max))
            limit_values = [_to_float(l.get("value")) for l in definition.get("limits") or []]
            if entry.trip_threshold is not None and limit_values and _to_float(entry.trip_threshold) not in limit_values:
                rows.append(("trip_threshold", ", ".join(f"{l.get('name')}={l.get('value')}" for l in definition.get("limits") or []),
                             entry.trip_threshold))
            for field, manual_value, opslens_value in rows:
                conflicts.append({
                    "tag": tag,
                    "definition_id": definition.get("id"),
                    "parameter": definition.get("parameter"),
                    "field": field,
                    "manual": manual_value,
                    "opslens": opslens_value,
                    "mapping": mapping.get("mapping"),
                    "source_page": definition.get("source_page"),
                    "resolution": "REPORTED — not changed automatically. Confirm the site value and update one source.",
                })
    return conflicts


def summary() -> Dict[str, Any]:
    ref = load_reference()
    defs = definitions()
    return {
        "source_document": ref.get("source_document"),
        "definition_count": len(defs),
        "applied_definitions": sum(1 for d in defs if (d.get("opslens_mapping") or {}).get("mapping") in APPLIED_MAPPINGS),
        "priority_convention": ref.get("priority_convention"),
        "known_gaps": ref.get("known_gaps") or [],
        "config_path": CONFIG_PATH.name,
    }
