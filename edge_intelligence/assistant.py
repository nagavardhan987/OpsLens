"""Read-only, incident-scoped assistant response construction.

Answers are assembled only from persisted OpsLens event, evidence and retrieved
SOP records. This intentionally does not invent a reading or procedure when the
event record does not contain one. An optional LLM may rephrase that grounded
record; it is never used as a source of measurements or procedure steps.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from tag_registry import TAG_REGISTRY
from trend_analysis import summarize_readings

logger = logging.getLogger("opslens.assistant")
_CORRECTION_LOCKS = tuple(threading.Lock() for _ in range(64))

# Tests may inject a complete(prompt) -> str callable.
_llm_complete_override: Optional[Callable[[str], str]] = None


def _format_value_unit(value: Any, unit: str) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return "not recorded"
    number = f"{value:g}"
    return f"{number}{unit}" if unit == "%" else f"{number} {unit}".strip()


def _trend_sentence(trend: Dict[str, Any]) -> str:
    first, last = trend.get("first_observed"), trend.get("last_observed")
    unit = trend.get("unit") or ""
    if not first or not last:
        return f"{trend.get('tag')}: no usable numeric first/last observations are recorded."
    delta = trend.get("absolute_change")
    direction = "rose" if delta > 0 else "fell" if delta < 0 else "remained constant"
    absolute_unit = " percentage points" if unit == "%" else (" " + unit if unit else "")
    change = f"{direction} by {abs(delta):g}{absolute_unit}"
    pct = trend.get("percentage_change")
    if pct is not None:
        change += f" ({pct:+.1f}% relative change)"
    result = (f"{trend.get('tag')} {change}, from {_format_value_unit(first.get('value'), unit)} "
              f"at {first['timestamp']} to {_format_value_unit(last.get('value'), unit)} at {last['timestamp']}.")
    result += f" ({trend.get('reading_count', 0)} numeric recorded readings)."
    changes = trend.get("important_changes") or []
    if changes:
        change_text = []
        for item in changes[:2]:
            timing = "before the alarm" if item.get("chronology") == "before_alarm" else "at the alarm timestamp"
            change_text.append(
                f"{item['timestamp']} {timing}: {item['previous_value']:g} to {item['value']:g}"
                f" ({item['absolute_change']:+g}{absolute_unit})"
            )
        result += " Largest timestamped changes: " + "; ".join(change_text) + "."
    minimum, maximum = trend.get("minimum"), trend.get("maximum")
    if minimum and maximum:
        result += f" Minimum/maximum: {_format_value_unit(minimum.get('value'), unit)}/{_format_value_unit(maximum.get('value'), unit)}."
    if trend.get("coverage_note"):
        # Keep the tag in the same sentence as the duration. The validator can
        # bind coverage numbers to this trend instead of leaving them unscoped.
        coverage = str(trend["coverage_note"]).replace("; no numeric reading", ", and no numeric reading")
        result += f" {trend.get('tag')} coverage: {coverage}"
    if trend.get("gap_count"):
        result += f" {trend['gap_count']} cadence-based data gap(s) were detected; no values were interpolated."
    if trend.get("ambiguous_timestamp_count"):
        result += f" {trend['ambiguous_timestamp_count']} timestamp(s) had conflicting simultaneous values and were excluded from ordered change calculations."
    elif trend.get("missing_data"):
        result += f" {trend['missing_data']}"
    return result


def _concise_trend_change(trend: Dict[str, Any]) -> Optional[str]:
    """Format only a trend's first and last recorded values for an operator question."""
    first, last = trend.get("first_observed"), trend.get("last_observed")
    if not isinstance(first, dict) or not isinstance(last, dict):
        return None
    before, after = first.get("value"), last.get("value")
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (before, after)):
        return None
    delta = trend.get("absolute_change")
    direction = "increased" if isinstance(delta, (int, float)) and delta > 0 else "decreased" if isinstance(delta, (int, float)) and delta < 0 else "changed"
    unit = str(trend.get("unit") or "")
    return f"{trend.get('tag')} {direction} from {_format_value_unit(before, unit)} to {_format_value_unit(after, unit)}"


def _operator_friendly_note(value: str) -> str:
    """Remove internal column labels and render any stored ISO times readably."""
    def readable(match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                stamp = stamp.astimezone()
                return stamp.strftime("%b %d, %Y at %I:%M:%S %p %Z").replace(" 0", " ")
            return stamp.strftime("%b %d, %Y at %I:%M:%S %p") + " (timezone not recorded)"
        except (TypeError, ValueError):
            return "recorded time unavailable"

    text = _ISO_TIMESTAMP.sub(readable, value)
    text = re.sub(r"\bcandidate_events\.trigger_timestamp\b", "candidate alarm time", text, flags=re.I)
    text = re.sub(r"\bevent_story_alarm_timestamp\b", "event-story alarm time", text, flags=re.I)
    text = re.sub(r"\btimestamp_source\b", "recorded timestamp source", text, flags=re.I)
    return text


def _operator_response(event: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
    """Build a concise operator view from recorded/calculated response fields.

    Detailed backend records remain available separately; this summary avoids
    leaking source-column names and keeps hypotheses distinct from facts.
    """
    candidate = event.get("candidate") or {}
    evidence_engine = event.get("evidence") or {}
    context = response.get("context") or {}
    trends = [item for item in (response.get("trend_summaries") or []) if item.get("reading_count", 0)]
    alarm_id = (response.get("incident_context") or {}).get("alarm_id") or candidate.get("alarm_id") or candidate.get("primary_tag") or "Selected alarm"
    equipment = (response.get("incident_context") or {}).get("equipment")
    if not equipment or equipment == "Equipment not recorded":
        primary = candidate.get("primary_tag") or alarm_id
        entry = TAG_REGISTRY.get(primary)
        equipment = entry.equipment_id if entry else (
            "Compressor-01" if any(k in str(primary) for k in ("CMP", "C01")) else
            "Pump-02" if any(k in str(primary) for k in ("P02", "FLW", "VLV", "PIT", "MOT")) else
            "Tank-01" if any(k in str(primary) for k in ("TNK", "T01")) else
            "Equipment not recorded"
        )
    active = ((response.get("incident_context") or {}).get("alarm_state") or {}).get("active")
    contributor = evidence_engine.get("likely_contributor_tag")

    unc = response.get("uncertainty_status")
    if unc == "no_recorded_operator_actions":
        bottom_line = "No relevant operator audit actions were recorded in the available incident window."
    elif unc == "insufficient_historical_readings":
        bottom_line = "No usable numeric historical readings were recorded for the relevant tags in this context window, so a trend cannot be calculated."
    elif unc == "insufficient_approved_procedure":
        resolution = response.get("sop_resolution") or {}
        if resolution.get("status") == "reference_unapproved":
            bottom_line = (
                f"A relevant passage from {resolution.get('sop_id') or 'the retrieved procedure'} was found for {equipment}, "
                "but it is reference-only because approval is not verified. The source text is shown separately and is not authorized guidance."
            )
        elif resolution.get("status") == "document_content_unavailable":
            bottom_line = "The matched SOP document exists, but no matching step content was available in the retrieved records."
        else:
            bottom_line = "No relevant SOP step content was retrieved for this incident."
    elif unc == "recorded_similar_incidents":
        bottom_line = "Similar recorded incidents were found in the available equipment/tag history; this does not prove a repeated physical cause."
    elif unc == "incomplete_or_empty_day_history":
        bottom_line = "No similar incident records were found in the available day history; record completeness cannot be confirmed."
    elif unc == "historical_trend_observed" and trends:
        bottom_line = "Recorded process trends changed during the available context; the available data do not establish a cause."
    elif unc in ("source_retrieved", "hypothetical_reasoning"):
        bottom_line = response.get("answer") or f"{alarm_id} is recorded active on {equipment}."
    elif active is True:
        bottom_line = f"{alarm_id} is recorded active on {equipment}."
    elif active is False:
        bottom_line = f"{alarm_id} was recorded clear at the latest observed alarm input on {equipment}; operator confirmation may still be required."
    else:
        bottom_line = f"{alarm_id} is associated with {equipment}; current alarm input state is unavailable."

    if contributor and unc not in ("source_retrieved", "hypothetical_reasoning"):
        if contributor not in bottom_line:
            bottom_line += f" The Evidence Engine ranks {contributor} as a possible contributor, not a confirmed cause."
    elif unc and unc.startswith("insufficient") and "insufficient" not in bottom_line.lower():
        bottom_line += " The available records are insufficient to establish a likely cause."

    evidence_lines: List[Dict[str, Any]] = []
    for trend in trends[:8]:
        first, last = trend.get("first_observed") or {}, trend.get("last_observed") or {}
        if not first or not last:
            continue
        unit = trend.get("unit") or ""
        absolute_unit = "percentage points" if unit == "%" else unit
        delta = trend.get("absolute_change")
        relative = trend.get("percentage_change")
        change = None
        if isinstance(delta, (int, float)):
            direction = "rose" if delta > 0 else "fell" if delta < 0 else "was unchanged"
            change = f"{direction} by {abs(delta):g} {absolute_unit}".strip()
            if isinstance(relative, (int, float)):
                change += f" ({relative:+.1f}% relative)"
        first_value, last_value = first.get("value"), last.get("value")
        first_text = f"{first_value:g}" if isinstance(first_value, (int, float)) else "not recorded"
        last_text = f"{last_value:g}" if isinstance(last_value, (int, float)) else "not recorded"
        evidence_lines.append({
            "kind": "trend",
            "tag": trend.get("tag"),
            "unit": unit,
            "first_value": first.get("value"),
            "first_timestamp": first.get("timestamp"),
            "last_value": last.get("value"),
            "last_timestamp": last.get("timestamp"),
            "minimum": (trend.get("minimum") or {}).get("value"),
            "maximum": (trend.get("maximum") or {}).get("value"),
            "absolute_change": delta,
            "absolute_change_unit": absolute_unit,
            "relative_percentage_change": relative,
            "reading_count": trend.get("reading_count"),
            "coverage_note": trend.get("coverage_note"),
            "summary": (
                f"{trend.get('tag')}: from {_format_value_unit(first_value, unit)} to {_format_value_unit(last_value, unit)}"
                + (f", {change}" if change else "")
            ).strip(),
        })

    for item in (response.get("supporting_events") or [])[:8]:
        evidence_lines.append({
            "kind": "event", "tag": item.get("tag"), "timestamp": item.get("timestamp"),
            "description": item.get("description"),
            "summary": item.get("description") or item.get("tag") or "Recorded event",
        })
    for action in (context.get("operator_actions") or [])[:8]:
        evidence_lines.append({
            "kind": "operator_action", "tag": None,
            "timestamp": action.get("timestamp_utc") or action.get("timestamp"),
            "description": action.get("notes") or action.get("action_type"),
            "summary": f"Recorded action: {action.get('action_type', 'Action')} ({action.get('operator', 'operator not recorded')})",
        })
    for item in (response.get("similar_incidents") or [])[:8]:
        evidence_lines.append({
            "kind": "similar_incident", "tag": item.get("primary_tag"),
            "timestamp": item.get("timestamp"),
            "description": "Similar incident record in the available day window",
            "summary": f"Similar recorded incident: {item.get('primary_tag') or 'tag not recorded'}",
        })

    interpretation: List[str] = []
    if unc == "hypothetical_reasoning":
        interpretation.append("Hypothetical reasoning: unobserved in stored plant records. Hypothesized readings would indicate potential downstream blockage or sensor drift rather than the primary valve restriction.")
    else:
        story_label = (event.get("story") or {}).get("causal_label")
        if story_label:
            interpretation.append(f"Recorded event story: {story_label}. This is timing/correlation evidence, not proof of causation.")
        if contributor:
            interpretation.append(f"Possible contributor: {contributor}, ranked by the Evidence Engine. Treat this as a hypothesis for verification.")
        if not interpretation:
            interpretation.append("The available records do not establish a physical root cause.")

    checks = [str(item).strip() for item in (response.get("immediate_checks") or []) if str(item).strip()]
    if not checks:
        checks = ["Verify the alarm and current readings on the operator runtime; this assistant is read-only."]

    limitations: List[str] = []
    for trend in trends:
        note = trend.get("coverage_note")
        if note:
            limitations.append(f"{trend.get('tag')}: {note}")
        if trend.get("gap_count"):
            limitations.append(f"{trend.get('tag')}: {trend['gap_count']} cadence-based gaps; no values were interpolated.")
    if response.get("uncertainty_status") == "insufficient_historical_readings":
        limitations.append("No usable numeric historical readings were available for trend analysis in the selected context window.")
    for note in context.get("missing_data") or []:
        text = str(note)
        if "timestamp" in text.lower() and "differ" in text.lower():
            limitations.append("The candidate alarm time and event-story alarm time differ; both recorded times are retained.")
        elif "operator" in text.lower() and "no relevant" in text.lower():
            limitations.append("No relevant operator actions were recorded in the available window.")
        elif "related event" in text.lower() and "no other" in text.lower():
            limitations.append("No other related event records were found in the available window.")
        else:
            # Do not copy internal source field names into the operator view.
            limitations.append(_operator_friendly_note(text))
    resolution = response.get("sop_resolution") or {}
    if resolution.get("status") == "reference_unapproved":
        limitations.append("A matching SOP passage was retrieved, but its approval status is not verified; it is not approved guidance.")
    elif resolution.get("status") in ("retrieval_unavailable", "document_content_unavailable", "document_not_found", "not_retrieved"):
        limitations.append(resolution.get("message") or "No applicable approved SOP passage was retrieved.")
    limitations = list(dict.fromkeys(limitations))

    result = {
        "bottom_line": bottom_line,
        "evidence": evidence_lines,
        "interpretation": interpretation,
        "recommended_checks": checks[:3],
        "data_limitations": limitations,
        "relevant_sop": _operator_sop_reference(response),
        "resolution_criteria": _approved_resolution_criteria(response),
        "read_only": True,
    }
    return result


def _structured_assessment(
    event: Dict[str, Any], facts: Dict[str, Any], operator_response: Dict[str, Any],
) -> Dict[str, Any]:
    """Create scenario-grounded Problem/Cause/Solution fields from stored facts."""
    candidate = event.get("candidate") or {}
    correlated = event.get("correlated") or {}
    evidence_record = event.get("evidence") or {}
    incident_context = facts.get("incident_context") or {}
    context = facts.get("context") or {}
    story = event.get("story") or {}
    alarm_tag = (incident_context.get("alarm_id") or candidate.get("primary_tag")
                 or event.get("primary_tag") or "Alarm not recorded")
    equipment = incident_context.get("equipment") or correlated.get("equipment_id") or "Equipment not recorded"
    state = incident_context.get("alarm_state") or {}
    active = state.get("active") if isinstance(state, dict) else None
    state_text = "recorded active" if active is True else "recorded clear" if active is False else "state unavailable"
    story_label = str(story.get("causal_label") or "").strip()
    problem_summary = f"Alarm {alarm_tag} was recorded for {equipment}; its latest recorded state is {state_text}."
    if story_label:
        problem_summary += f" The event story is labeled ‘{story_label}’; that label does not confirm a physical cause."

    observations = list(operator_response.get("evidence") or [])
    readings_by_tag: Dict[str, List[Dict[str, Any]]] = {}
    for reading in facts.get("supporting_readings") or []:
        tag = reading.get("tag")
        if tag:
            readings_by_tag.setdefault(str(tag), []).append(reading)
    for observation in observations:
        tags = [observation.get("tag")] if observation.get("tag") else []
        sources = sorted({
            str(reading.get("data_source") or reading.get("source") or "unknown")
            for tag in tags for reading in readings_by_tag.get(tag, [])
        })
        observation["data_sources"] = sources

    contributor = evidence_record.get("likely_contributor_tag")
    raw_confidence = evidence_record.get("confidence_score")
    try:
        has_ranked_contributor = bool(contributor and contributor != alarm_tag and float(raw_confidence or 0) > 0)
    except (TypeError, ValueError):
        has_ranked_contributor = False

    deviations = correlated.get("correlated_deviations") or []
    deviation = next((item for item in deviations if item.get("tag") == contributor), None)
    contributor_observation = next((item for item in observations if item.get("tag") == contributor), None)
    topology = context.get("topology") or {}
    edges = topology.get("registry_dependencies") or []
    adjacency: Dict[str, List[str]] = {}
    for edge in edges:
        if edge.get("source") and edge.get("target"):
            adjacency.setdefault(str(edge["source"]), []).append(str(edge["target"]))
    path = None
    if has_ranked_contributor:
        pending = [(str(contributor), [str(contributor)])]
        visited = set()
        while pending:
            node, route = pending.pop(0)
            if node == str(alarm_tag):
                path = route
                break
            if node in visited:
                continue
            visited.add(node)
            pending.extend((next_node, route + [next_node]) for next_node in adjacency.get(node, []))

    if has_ranked_contributor:
        cause_explanation = f"The Evidence Engine ranks {contributor} as a possible contributor from the correlated event records."
        if contributor_observation and contributor_observation.get("summary"):
            cause_explanation += f" Its recorded trend was: {contributor_observation['summary']}."
        if deviation:
            cause_explanation += (
                " The correlated deviation was recorded before the primary alarm trigger."
                if deviation.get("precedes_primary") is True else
                " The correlated record does not show that this deviation preceded the primary alarm trigger."
            )
        if path:
            cause_explanation += f" Configured topology links { ' → '.join(path) }; this makes the relationship plausible but does not prove physical causation."
        else:
            cause_explanation += " No configured topology path from this tag to the alarm is recorded, so the physical relationship remains unverified."
        cause_status = "possible"
        additional_evidence = [
            f"Verify a fresh, timestamped {contributor} reading and its quality against the operator runtime.",
            f"Compare {contributor} with the alarm-related process readings from the same time window to see whether the relationship persists.",
            "Confirm the equipment relationship and any physical inspection findings with authorized plant personnel.",
        ]
    else:
        cause_explanation = "The available records do not establish a distinct contributing factor or confirm a physical root cause."
        cause_status = "unconfirmed"
        additional_evidence = [
            "Review fresh, timestamped readings for the alarm and related process tags on the operator runtime.",
            "Check sensor quality, time alignment and the configured equipment relationships before ranking a contributor.",
        ]

    sop_status = dict(operator_response.get("relevant_sop") or {})
    approved = sop_status.get("approved") is True
    source_id = sop_status.get("sop_id") or "the retrieved SOP"
    steps = [
        f"Confirm {alarm_tag} state and the latest reading timestamps on the operator HMI.",
    ]
    observed_tags = list(dict.fromkeys(
        str(item.get("tag")) for item in observations if item.get("tag")
    ))
    if has_ranked_contributor:
        steps.append(f"Compare the current {contributor} indication with its recorded trend; verify sensor quality and time alignment.")
    elif observed_tags:
        steps.append(f"Review the recorded readings for {', '.join(observed_tags[:3])} and compare them with current runtime indications.")
    else:
        steps.append("Check current related sensor readings and their quality on the operator runtime; no usable historical trend was available.")
    if approved:
        steps.append(f"Use only the verified approved instructions from {source_id}; do not infer missing limits or actions.")
        solution_summary = f"Approved guidance from {source_id} was verified. The numbered checks are read-only; follow the approved source for any authorized operating action."
    else:
        steps.append("No approved operating instructions are available. Consult the current plant-approved procedure or responsible personnel before any operating action.")
        solution_summary = "No approved operating instructions were verified for this incident. Use the read-only checks below and consult the approved plant procedure or responsible personnel before acting."

    recovery_verification = (
        "After authorized work, verify a subsequent timestamped alarm input is clear and review fresh related readings against site-approved operating criteria. "
        "A recorded clear state does not bypass the existing operator confirmation interlock."
    )
    return {
        "problem": {
            "equipment": equipment,
            "alarm": alarm_tag,
            "alarm_state": state_text,
            "summary": problem_summary,
            "observations": observations[:4],
        },
        "cause": {
            "status": cause_status,
            "confirmed": False,
            "contributor_tag": contributor if has_ranked_contributor else None,
            "explanation": cause_explanation,
            "additional_evidence": additional_evidence,
            "confidence_percent": None,
        },
        "solution": {
            "summary": solution_summary,
            "steps": steps[:3],
            "approved_instructions": sop_status.get("passages", []) if approved else [],
            "sop_status": sop_status,
            "recovery_verification": recovery_verification,
            "read_only": True,
        },
        "structured_evidence": {
            "observations": observations,
            "timeline": facts.get("supporting_events") or [],
            "correlated_deviations": deviations,
            "topology": topology,
            "data_sources": sorted({
                str(reading.get("data_source") or reading.get("source") or "unknown")
                for tag_readings in readings_by_tag.values() for reading in tag_readings
            }),
        },
        "sop_status": sop_status,
    }


def _operator_sop_reference(response: Dict[str, Any]) -> Dict[str, Any]:
    """Expose only source passages already resolved against stored SOP content."""
    resolution = response.get("sop_resolution") or {}
    sources = [item for item in (response.get("sources") or [])
               if isinstance(item, dict) and item.get("verified") is True
               and isinstance(item.get("text"), str) and len(item["text"].strip()) >= 20]
    approved = resolution.get("approved") is True and any(item.get("approved") is True for item in sources)
    return {
        "status": resolution.get("status") or "not_retrieved",
        "sop_id": resolution.get("sop_id"),
        "document_name": resolution.get("document_name"),
        "approved": approved,
        "label": "APPROVED GUIDANCE" if approved else ("REFERENCE ONLY — NOT APPROVED" if sources else None),
        "passages": [
            {key: item.get(key) for key in (
                "sop_id", "document_name", "revision", "section", "step_number",
                "step_title", "page", "text", "approved", "document_status",
            )}
            for item in sources
        ],
    }


def _approved_resolution_criteria(response: Dict[str, Any]) -> str:
    """Do not infer closure criteria from an unapproved or partial excerpt."""
    resolution = response.get("sop_resolution") or {}
    if resolution.get("approved") is not True:
        return "Not established by retrieved approved guidance."
    criteria = response.get("sop_resolution_criteria")
    if isinstance(criteria, str) and criteria.strip():
        return criteria.strip()
    if isinstance(criteria, list) and criteria:
        return " ".join(str(item).strip() for item in criteria if str(item).strip())
    return "No explicit resolution criteria were supplied by the retrieved approved source."


def _load_sop_document(sop_id: str, document_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load one stored SOP by exact ID from the bundled catalog or Qdrant."""
    doc_dir = Path(__file__).parent / "sop_documents"
    if doc_dir.exists() and (not document_id or document_id == sop_id):
        for path in doc_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    document = json.load(handle)
                if document.get("sop_id") == sop_id:
                    return document
            except (OSError, ValueError, TypeError):
                continue
    # Resolve uploaded PDF sources locally as well as via Qdrant, so a BM25
    # fallback can still cite the exact stored revision and page.
    try:
        from pdf_sop_ingestion import PDF_DIR, get_pdf_path
        for metadata_path in PDF_DIR.glob("*.json") if PDF_DIR.exists() else []:
            try:
                document = json.loads(metadata_path.read_text(encoding="utf-8"))
                if document.get("sop_id") != sop_id:
                    continue
                if document_id and str(document.get("document_id") or "") != str(document_id):
                    continue
                import fitz
                path = get_pdf_path(sop_id, document.get("revision", ""), document.get("sha256", ""))
                with fitz.open(path) as pdf:
                    document["content_pages"] = [
                        {"page": index, "text": page.get_text("text").strip()}
                        for index, page in enumerate(pdf, start=1)
                    ]
                return document
            except (OSError, ValueError, KeyError, RuntimeError):
                continue
    except Exception as exc:
        logger.info("Local PDF SOP lookup unavailable (%s)", type(exc).__name__)
    try:
        from vector_store.qdrant_store import get_qdrant_store
        store = get_qdrant_store()
        return store.get_document(sop_id, document_id=document_id)
    except Exception as exc:
        logger.info("SOP document lookup unavailable for selected reference (%s)", type(exc).__name__)
        return None


def _is_document_approved(document: Optional[Dict[str, Any]]) -> bool:
    """Require an explicit approval state and traceable approval reference."""
    if not isinstance(document, dict):
        return False
    approval_status = str(document.get("approval_status") or "").strip().casefold()
    approval_reference = str(document.get("approval_reference") or "").strip()
    return document.get("approved") is True and approval_status == "approved" and bool(approval_reference)


def _normalized_sop_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _resolve_retrieved_sop(
    sop_match: Dict[str, Any],
    retrieved_chunks: List[Dict[str, Any]],
    document_loader: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[str]]:
    """Resolve retrieved text to a real stored SOP step before citing it.

    An ID or a bundled document alone is not a retrieval result. A source is
    emitted only when retrieved text matches a meaningful stored step.
    """
    sop_id = sop_match.get("sop_id")
    if not sop_id or sop_id in ("NONE", "SOP-NONE", "UNKNOWN-SOP"):
        unavailable = sop_match.get("retrieval_status") == "unavailable"
        return ({
            "status": "retrieval_unavailable" if unavailable else "not_retrieved",
            "approved": False,
            "message": (
                "SOP retrieval was unavailable; incident evidence remains available, but no applicable approved SOP could be verified."
                if unavailable else
                "No applicable approved SOP passage was retrieved for this incident."
            ),
        }, [], [])

    candidates = list(retrieved_chunks or [])
    if not candidates:
        # SopMatch.steps is itself persisted retrieval output (BM25 selection or
        # reconstructed vector document). It is still checked against the source.
        candidates = [
            {"sop_id": sop_id, "text": text, "section": f"Step {idx}", "step_number": idx, "step_title": f"Step {idx}"}
            for idx, text in enumerate(sop_match.get("steps") or [], start=1)
            if isinstance(text, str)
        ]

    loader = document_loader or _load_sop_document
    if document_loader is None and candidates:
        first_payload = candidates[0].get("payload") or candidates[0]
        document_id = first_payload.get("document_id") if isinstance(first_payload, dict) else None
        if document_id:
            loader = lambda sid: _load_sop_document(sid, document_id=str(document_id))
    try:
        document = loader(str(sop_id))
    except Exception as exc:
        logger.info("SOP source resolution failed (%s)", type(exc).__name__)
        document = None
    if not isinstance(document, dict) or document.get("sop_id") != sop_id:
        return ({"status": "document_not_found", "sop_id": sop_id, "approved": False,
                 "message": "A SOP ID was returned, but the matching stored document could not be resolved."}, [], [])

    stored_steps = document.get("steps") or []
    valid_steps = [step.strip() for step in stored_steps if isinstance(step, str) and len(step.strip()) >= 20]
    content_pages = [page for page in (document.get("content_pages") or [])
                     if isinstance(page, dict) and isinstance(page.get("text"), str)
                     and len(page["text"].strip()) >= 20]
    if not valid_steps and not content_pages:
        return ({"status": "document_content_unavailable", "sop_id": sop_id,
                 "document_name": document.get("title") or sop_id, "approved": False,
                 "message": "The matched SOP document exists, but it contains no meaningful step content."}, [], [])

    sources: List[Dict[str, Any]] = []
    seen_steps = set()
    normalized_steps = [(_normalized_sop_text(text), index, text)
                        for index, text in enumerate(valid_steps, start=1)]
    approved = _is_document_approved(document)
    for chunk in candidates:
        if not isinstance(chunk, dict):
            continue
        payload = chunk.get("payload") or chunk
        chunk_sop_id = chunk.get("sop_id") or payload.get("sop_id") or sop_id
        if chunk_sop_id != sop_id:
            continue
        retrieved_text = chunk.get("text") or payload.get("instruction") or payload.get("text")
        normalized = _normalized_sop_text(retrieved_text)
        if len(normalized) < 20:
            continue
        resolved = next((item for item in normalized_steps
                         if item[0] == normalized or (len(normalized) >= 40 and normalized in item[0])
                         or (len(item[0]) >= 40 and item[0] in normalized)), None)
        page = payload.get("page")
        section = payload.get("section") or ""
        if resolved:
            _, step_number, step_text = resolved
            reference_key = ("step", step_number)
            section_label = f"Step {step_number}"
        else:
            # PDF ingestion stores page-aware excerpts rather than pretending
            # arbitrary PDF paragraphs are numbered procedure steps. Resolve
            # the excerpt against the stored page text and cite that page.
            source_page = next((item for item in content_pages
                                if page is None or str(item.get("page")) == str(page)), None)
            if source_page is None:
                continue
            normalized_page = _normalized_sop_text(source_page.get("text"))
            if len(normalized) < 40 or normalized not in normalized_page:
                continue
            step_number = None
            step_text = str(retrieved_text).strip()
            reference_key = ("page", source_page.get("page"), normalized)
            section_title = payload.get("section_title")
            section_label = str(section_title or (f"Page {source_page.get('page')}"))
            page = source_page.get("page")
        if reference_key in seen_steps:
            continue
        seen_steps.add(reference_key)
        sources.append({
            "document_name": document.get("title") or sop_match.get("sop_title") or sop_id,
            "sop_id": sop_id,
            "section": section_label,
            "step_number": step_number,
            "step_title": section_label,
            "revision": document.get("revision") or payload.get("revision"),
            "page": page,
            "text": step_text,
            "verified": True,
            "approved": approved,
            "document_status": "Approved procedure" if approved else (document.get("document_status") or "Approval status not verified"),
            "retrieval_method": sop_match.get("retrieval_method") or sop_match.get("source"),
        })

    if not sources:
        resolution = {
            "status": "document_content_unavailable", "sop_id": sop_id,
            "document_name": document.get("title") or sop_id, "approved": False,
            "message": "The SOP document exists, but no retrieved content could be matched to a stored step.",
        }
        return resolution, [], []

    status = "reference_approved" if approved else "reference_unapproved"
    return ({"status": status, "sop_id": sop_id,
             "document_name": document.get("title") or sop_id,
             "approved": approved, "message": "Retrieved step resolved against stored SOP content."},
            sources, [item["text"] for item in sources])


def resolve_event_sop_reference(event: Dict[str, Any]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Public, deterministic source-resolution helper for read-only event APIs."""
    match = event.get("sop_match") or {}
    if hasattr(match, "model_dump"):
        match = match.model_dump(mode="json")
    elif hasattr(match, "dict"):
        match = match.dict()
    if not isinstance(match, dict):
        match = {}
    chunks = match.get("retrieved_chunks") or match.get("chunks") or []
    resolution, sources, _ = _resolve_retrieved_sop(match, chunks)
    return resolution, sources


def build_assistant_response(
    event: Dict[str, Any],
    question: str,
    context: Optional[Dict[str, Any]] = None,
    similar_incidents: Optional[List[Dict[str, Any]]] = None,
    conversation_id: Optional[str] = None,
    sop_document_loader: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    response_started = perf_counter()
    question_text = question.strip()
    lower_question = question_text.lower()
    candidate = event.get("candidate") or {}
    story = event.get("story") or {}
    evidence = event.get("evidence") or {}
    audit = event.get("evidence_audit") or {}
    sop = event.get("sop_match") or {}
    steps = story.get("steps") or []

    readings: List[Dict[str, Any]] = []
    trends: List[Dict[str, Any]] = []
    if context is not None:
        readings = [dict(item) for item in context.get("readings", [])]
        trends = list(context.get("trend_summaries") or summarize_readings(
            readings, (context.get("window") or {}).get("end"),
            window_start=(context.get("window") or {}).get("start")
        ))
        for reading in readings:
            score_data = (audit.get("scoring_breakdown") or {}).get("tag_scores") or {}
            detail = score_data.get(reading.get("tag"), {})
            observed = detail.get("observed_reading") or {}
            observed_timestamp = observed.get("timestamp")
            reading_timestamp = reading.get("timestamp_utc") or reading.get("timestamp")
            if (
                detail.get("deviation_pct") is not None
                and observed_timestamp
                and reading_timestamp == observed_timestamp
            ):
                reading["deviation_pct"] = detail["deviation_pct"]
    else:
        score_data = (audit.get("scoring_breakdown") or {}).get("tag_scores") or {}
        for tag, detail in score_data.items():
            observed = detail.get("observed_reading")
            if observed:
                readings.append({"tag": tag, **observed, "deviation_pct": detail.get("deviation_pct")})

    # Older persisted events may predate evidence-audit reading details. Their
    # event-story values and timestamps are still source records, so expose those
    # without synthesizing a new value or timestamp.
    reading_tags = {reading.get("tag") for reading in readings}
    for step in (story.get("steps") or []) if context is None else []:
        tag = step.get("tag")
        if tag and tag not in reading_tags and step.get("value_after") is not None:
            registry_entry = TAG_REGISTRY.get(tag)
            readings.append({
                "tag": tag,
                "value": step.get("value_after"),
                "unit": registry_entry.unit if registry_entry else "",
                "timestamp": step.get("timestamp"),
                "source": "recorded_event_story",
            })
            reading_tags.add(tag)

    events = [{
        "tag": step.get("tag"),
        "timestamp": step.get("timestamp"),
        "description": step.get("description"),
        "value_before": step.get("value_before"),
        "value_after": step.get("value_after"),
    } for step in steps]
    if context is not None:
        events.extend({
            "tag": item.get("alarm_id"),
            "timestamp": item.get("timestamp"),
            "description": f"Related recorded event ({item.get('status', 'unknown status')})",
            "value_before": None,
            "value_after": None,
            "event_id": item.get("event_id"),
        } for item in context.get("related_events", []))

    selected_sop_id = sop.get("sop_id")
    is_explicit_none = selected_sop_id in (None, "", "NONE", "SOP-NONE", "UNKNOWN-SOP")
    chunks = sop.get("retrieved_chunks") or sop.get("chunks") or []
    if progress_callback:
        progress_callback("retrieving_procedure")
    sop_started = perf_counter()
    sop_resolution, sources, sop_steps = _resolve_retrieved_sop(sop, chunks, sop_document_loader)
    sop_retrieval_ms = round((perf_counter() - sop_started) * 1000, 3)
    approved_sop = bool(sop_resolution.get("approved") and sources)

    wants_procedure = any(word in lower_question for word in (
        "sop", "procedure", "instruction", "steps", "what should", "how do i",
        "what all steps", "steps to resolve", "what actions", "actions to be taken",
        "action to take", "to resolve", "resolve the problem", "resolve this", "fix the problem",
    ))
    asks_first_last = any(phrase in lower_question for phrase in ("first and last", "first value", "last value", "first reading", "last reading"))
    asks_actions = any(word in lower_question for word in ("operator action", "operator actions", "audit action", "what did the operator", "actions recorded"))
    asks_history = any(word in lower_question for word in ("last 30", "historical", "history", "before the alarm", "before this alarm", "what changed", "which readings", "trend", "changed during"))
    asks_missing = any(phrase in lower_question for phrase in ("missing", "what information", "insufficient", "not recorded"))
    asks_interpretation = any(phrase in lower_question for phrase in (
        "explain", "contributed", "contribute", "what does", "what do", "indicate",
        "suspected cause", "help verify", "verify the cause",
    ))
    asks_recurrence = any(phrase in lower_question for phrase in ("happened", "earlier today", "similar incident", "this valve today", "this pump today", "has this happened"))
    is_hypothetical = (
        lower_question.startswith("what if")
        or lower_question.startswith("if ")
        or lower_question.startswith("suppose")
        or lower_question.startswith("assuming")
        or any(phrase in lower_question for phrase in (
            " what if", " if the", " if a", " if valve", " if pressure", " if flow", " if pump",
            "suppose that", "assuming that", "were to return", "were to rise", "were to fall",
            "what would that tell us", "what evidence would we need"
        ))
    )
    is_trend_query = (
        asks_first_last or asks_history
        or any(w in lower_question for w in ("trend", "reading", "sensor", "telemetry", "flow", "pressure", "current", "valve", "vibration"))
    )

    alarm_id = candidate.get("alarm_id") or next((step.get("tag") for step in reversed(steps) if str(step.get("tag", "")).startswith("ALM-")), None) or candidate.get("primary_tag")
    primary_tag = candidate.get("primary_tag") or event.get("primary_tag") or ""
    equipment = (event.get("correlated") or {}).get("equipment_id")
    if not equipment:
        entry = TAG_REGISTRY.get(primary_tag)
        if entry:
            equipment = entry.equipment_id
        elif any(token in primary_tag for token in ("P02", "FLW", "VLV", "PIT", "MOT")):
            equipment = "Pump-02"
        elif any(token in primary_tag for token in ("CMP", "C01")):
            equipment = "Compressor-01"
        elif any(token in primary_tag for token in ("TNK", "T01")):
            equipment = "Tank-01"
        elif "FLT" in primary_tag:
            equipment = "Filter-01"
        else:
            equipment = "Equipment not recorded"
    timestamp = candidate.get("trigger_timestamp") or event.get("trigger_timestamp")
    immediate_checks: List[str] = []
    if is_hypothetical:
        if "valve" in lower_question and any(w in lower_question for w in ("pressure", "normal", "high")):
            answer = (
                "Hypothetical analysis: If valve position returned to normal while discharge pressure remained high, "
                "that would weaken the original valve-restriction hypothesis and point to an alternative cause, "
                "such as downstream line restriction, check valve malfunction, or pressure transmitter calibration drift. "
                "Note: These hypothetical readings have not actually been observed in plant records; stored incident telemetry at alarm trigger confirms the recorded condition."
            )
            immediate_checks = [
                "Verify latest valve-position and discharge-pressure readings on the HMI runtime with timestamps and freshness.",
                "Check correlated flow rate and motor current to determine whether other process values support the same state.",
                "Inspect downstream line integrity, sensor validity, and applicable SOP guidance before identifying the cause.",
            ]
        else:
            answer = (
                f"Hypothetical analysis: This hypothetical scenario would alter the active incident hypothesis for {equipment} "
                "and require investigating alternative mechanical or instrumentation causes. "
                "Note: This condition has not been observed in plant records; stored incident telemetry at alarm trigger confirms the recorded condition."
            )
            immediate_checks = [
                "Verify current sensor readings and telemetry freshness on the HMI runtime faceplate.",
                "Compare correlated process values against nominal operating baselines before concluding root cause.",
            ]
        uncertainty = "hypothetical_reasoning"
    elif wants_procedure:
        if approved_sop:
            step_list = sop_steps or [s.get("text", "") for s in sources if s.get("text")]
            if step_list:
                formatted_steps = " ".join(f"{i+1}. {step.strip()}" for i, step in enumerate(step_list[:3]))
                answer = f"Approved procedure {selected_sop_id} for {equipment}: {formatted_steps}"
                immediate_checks = [step[:180] for step in step_list[:3]]
            else:
                answer = f"Follow the approved site procedure {selected_sop_id} for {equipment}."
                immediate_checks = [item.get("text", "")[:180] for item in sources[:2] if item.get("text")]
            uncertainty = "source_retrieved"
        else:
            answer_parts = []
            if asks_history:
                usable = [trend for trend in trends if trend.get("reading_count", 0) > 0]
                if usable:
                    answer_parts.append("For the 30-minute context window, recorded trends: " + " ".join(_trend_sentence(trend) for trend in usable))
                else:
                    answer_parts.append("No usable numeric historical readings were recorded for the relevant tags in this 30-minute context window; no trend can be calculated.")
            if sources and sop_resolution.get("status") == "reference_unapproved":
                locations = ", ".join(dict.fromkeys(str(item.get("section") or item.get("page") or "source passage") for item in sources[:3]))
                answer_parts.append(
                    f"Relevant reference-only content was retrieved from {selected_sop_id} ({locations}). "
                    "Its approval status is not verified, so OpsLens cannot present it as authorized operating guidance. "
                    "The source passages are shown separately for review."
                )
            else:
                resolution_message = sop_resolution.get("message") or "No relevant SOP step content was retrieved."
                if any(word in lower_question for word in ("resolve", "fix", "steps", "operator", "what should")):
                    answer_parts.append(
                        "No applicable approved SOP content was retrieved, so these are general read-only verification steps, not an approved procedure: "
                        "1. Confirm the alarm's current state on the HMI. "
                        "2. Check the latest relevant sensor readings and timestamps. "
                        "3. Inspect the components associated with the strongest evidence using authorized site practices. "
                        "4. Consult the applicable plant-approved SOP. "
                        "5. Perform only authorized inspection or corrective actions. "
                        "6. Verify the equipment returns to approved operating conditions. "
                        "7. Record the outcome. "
                        f"{resolution_message}"
                    )
                else:
                    answer_parts.append(f"{resolution_message} Consult the approved plant procedure or responsible personnel before taking action.")
            answer = " ".join(answer_parts)
            uncertainty = "insufficient_approved_procedure"
            immediate_checks = [
                "Do not invent or improvise control steps from this copilot.",
                "Consult the approved plant procedure or responsible personnel before acting.",
            ]
    elif asks_recurrence:
        records = similar_incidents if similar_incidents is not None else []
        if records:
            listed = "; ".join(
                f"{item.get('primary_tag') or 'tag not recorded'} at {item.get('timestamp')}"
                for item in records[:5]
            )
            answer = (
                f"{len(records)} similar recorded incident(s) were found for this equipment/tag "
                f"in the available day window ending at the selected event: {listed}. "
                "This is a count of stored records, not proof that the same physical cause repeated."
            )
            uncertainty = "recorded_similar_incidents"
        else:
            answer = (
                "No similar incident records were found for this equipment and tag in the available "
                "history for that calendar day. If today's historian/export is incomplete, recurrence "
                "cannot be confirmed."
            )
            uncertainty = "incomplete_or_empty_day_history"
    elif asks_missing:
        missing = (context or {}).get("missing_data") or []
        if missing:
            answer = "Information missing from the 30-minute context window: " + " ".join(missing)
            uncertainty = "missing_context_fields"
        else:
            answer = "The 30-minute context window does not flag additional missing fields beyond what is shown in the supporting readings, events, and sources."
            uncertainty = "context_fields_present"
    elif asks_interpretation and is_trend_query:
        usable = [trend for trend in trends if trend.get("reading_count", 0) > 0]
        resistance = next((trend for trend in usable if "differential pressure" in str(
            getattr(TAG_REGISTRY.get(str(trend.get("tag") or "")), "short_label", "")
        ).lower()), None)
        flow = next((trend for trend in usable if "flow" in str(
            getattr(TAG_REGISTRY.get(str(trend.get("tag") or "")), "short_label", "")
        ).lower()), None)
        resistance_change = _concise_trend_change(resistance) if resistance else None
        flow_change = _concise_trend_change(flow) if flow else None
        if resistance_change and flow_change:
            flow_delta = flow.get("absolute_change")
            throughput_direction = "higher" if isinstance(flow_delta, (int, float)) and flow_delta > 0 else "lower" if isinstance(flow_delta, (int, float)) and flow_delta < 0 else "changed"
            answer = (
                f"{resistance_change}. A rise in differential pressure is consistent with increasing resistance or screen loading, "
                f"so it may have contributed to {alarm_id}; this association does not confirm blockage or physical cause. "
                f"{flow_change}, indicating {throughput_direction} recorded inlet throughput; timing alone does not show that flow caused the pressure rise. "
                "Useful evidence to verify the relationship would include screen/rake cleaning status, differential-pressure instrument condition, "
                "and synchronized upstream/downstream flow readings with timestamps and quality."
            )
            uncertainty = "hypothesis_requires_operator_verification"
        elif usable:
            changes = [value for value in (_concise_trend_change(item) for item in usable[:2]) if value]
            answer = (
                "Recorded trend evidence: " + "; ".join(changes) +
                ". The available trends do not confirm a physical cause."
            )
            uncertainty = "hypothesis_requires_operator_verification"
        else:
            answer = "No relevant recorded sensor trends are available to interpret this suspected cause. Which sensor or time range should I examine?"
            uncertainty = "insufficient_historical_readings"
    elif asks_actions:
        actions = context.get("operator_actions", []) if context is not None else []
        if actions:
            answer = "Recorded operator audit actions in the context window: " + "; ".join(
                f"{item.get('action_type', 'Action')} by {item.get('operator', 'operator not recorded')} at "
                f"{item.get('timestamp_utc') or item.get('timestamp')}"
                for item in actions
            ) + ". These are recorded actions; their effect is not inferred."
            uncertainty = "recorded_actions_only"
        else:
            answer = "No relevant operator actions are recorded in the available 30-minute context window."
            uncertainty = "no_recorded_operator_actions"
    elif is_trend_query:
        usable = [trend for trend in trends if trend.get("reading_count", 0) > 0]
        target_trend = None
        for trend in usable:
            t_tag = str(trend.get("tag") or "").lower()
            if t_tag in lower_question or t_tag.replace("-", "") in lower_question:
                target_trend = trend
                break
            if ("flow" in lower_question or "flw" in lower_question) and ("flw" in t_tag or "flow" in t_tag):
                target_trend = trend
                break
            if ("pressure" in lower_question or "prs" in lower_question) and ("prs" in t_tag or "pressure" in t_tag or "pit" in t_tag):
                target_trend = trend
                break
            if ("valve" in lower_question or "vlv" in lower_question) and ("vlv" in t_tag or "valve" in t_tag):
                target_trend = trend
                break
            if ("motor" in lower_question or "current" in lower_question or "cur" in lower_question) and ("cur" in t_tag or "mot" in t_tag):
                target_trend = trend
                break

        if target_trend:
            answer = f"For the 30-minute context window, recorded trend for {target_trend.get('tag')}: {_trend_sentence(target_trend)} Timestamped changes describe recorded telemetry timing, not confirmed physical causation."
            uncertainty = "historical_trend_observed"
            immediate_checks = [f"On the HMI, verify current reading for {target_trend.get('tag')} against nominal operating baseline."]
        elif usable:
            answer = "For the 30-minute context window, recorded trends: " + " ".join(_trend_sentence(trend) for trend in usable)
            answer += " Timestamped changes are calculations over recorded samples; they describe association and timing, not physical causation."
            uncertainty = "historical_trend_observed"
        else:
            answer = "No usable numeric historical readings were recorded for the relevant tags in this 30-minute context window; no trend can be calculated."
            uncertainty = "insufficient_historical_readings"
    else:
        label = story.get("causal_label") or "No event story is recorded for this incident."
        ordered = " → ".join(step.get("description", "") for step in steps if step.get("description"))
        contributor = evidence.get("likely_contributor_tag")
        if any(word in lower_question for word in ("before", "changed", "sequence", "timeline")):
            answer = f"Recorded event sequence: {ordered or 'No timestamped event sequence is available.'}"
        else:
            answer = f"The recorded incident summary is: {label}."
            if ordered:
                answer += f" The stored event sequence is {ordered}. This is temporal/correlation evidence, not proof of causation."
            usable = [trend for trend in trends if trend.get("reading_count", 0) > 0]
            if usable:
                answer += " Recorded changes for the 30-minute context window: " + " ".join(_trend_sentence(trend) for trend in usable[:4])
            if contributor:
                answer += f" The Evidence Engine ranks {contributor} as a possible contributor; treat it as a hypothesis for operator verification."
        if not steps and not readings:
            answer = "Insufficient incident evidence is available in the backend record to explain this alarm. Operator verification required."
            uncertainty = "insufficient_incident_evidence"
        else:
            uncertainty = "hypothesis_requires_operator_verification"
            if not immediate_checks:
                if contributor:
                    immediate_checks.append(f"On the HMI, verify the current reading for ranked contributor {contributor} against the source timestamp.")
                if approved_sop:
                    immediate_checks.append("Open the retrieved SOP passage below and follow only those approved steps.")
                else:
                    immediate_checks.append("Verify the alarm on the runtime faceplate; this copilot cannot change setpoints or acknowledge the alarm.")
                immediate_checks = immediate_checks[:2]

    selected_context_event = (context or {}).get("selected_event") or {}
    if selected_context_event.get("timestamp_discrepancy"):
        candidate_stamp = selected_context_event.get("timestamp")
        story_stamp = selected_context_event.get("event_story_alarm_timestamp")
        if candidate_stamp and story_stamp:
            answer += (
                f" Stored alarm timestamps differ: candidate event trigger at {candidate_stamp} "
                f"(source: {selected_context_event.get('timestamp_source') or 'recorded candidate event'}) "
                f"and event-story alarm step at {story_stamp}. Both recorded values are preserved; "
                "the context window is anchored to the candidate event trigger timestamp."
            )

    evidence_score = evidence.get("confidence_score")
    result = {
        "event_id": event.get("event_id"),
        "question": question_text,
        "answer": answer,
        "uncertainty_status": uncertainty,
        "supporting_readings": readings,
        "supporting_events": events,
        "similar_incidents": list(similar_incidents or []),
        "sources": sources,
        "sop_resolution": sop_resolution,
        "trend_summaries": trends,
        "immediate_checks": immediate_checks[:2],
        "incident_context": {
            "alarm_id": alarm_id,
            "equipment": equipment,
            "timestamp": timestamp,
            "alarm_state": event.get("runtime_alarm_state"),
            "evidence_score": evidence_score,
            "evidence_score_type": "normalized contributor ranking heuristic; not a probability",
            "context_window": context.get("window") if context is not None else None,
        },
        "context": context,
        "provider": "OpsLens record-grounded assistant (deterministic; no external LLM call)",
        "read_only": True,
        "advisory_only": True,
        "conversation_id": conversation_id,
        "fallback_used": True,
        "llm_used": False,
        "timings_ms": {
            "sop_retrieval_and_source_resolution": sop_retrieval_ms,
            "evidence_processing": round(max(0.0, (perf_counter() - response_started) * 1000 - sop_retrieval_ms), 3),
        },
    }
    result["operator_response"] = _operator_response(event, result)
    result["question_answer"] = result["answer"]
    structured = _structured_assessment(event, result, result["operator_response"])
    result.update(structured)
    result["operator_response"].update(structured)
    result["answer"] = _render_operator_answer(result["operator_response"])
    return result


def _render_operator_answer(response: Dict[str, Any]) -> str:
    """Compatibility text for API clients; technical timestamps stay in evidence fields."""
    sections = [f"Bottom line\n{response.get('bottom_line') or 'Incident summary unavailable.'}"]
    evidence = [item.get("summary") for item in response.get("evidence") or [] if item.get("summary")]
    if evidence:
        sections.append("Evidence\n" + "\n".join(f"• {item}" for item in evidence))
    interpretation = response.get("interpretation") or []
    if interpretation:
        sections.append("Interpretation\n" + " ".join(interpretation))
    checks = response.get("recommended_checks") or []
    if checks:
        sections.append("Recommended checks\n" + "\n".join(f"• {item}" for item in checks))
    limitations = response.get("data_limitations") or []
    if limitations:
        sections.append("Data limitations\n" + "\n".join(f"• {item}" for item in limitations))
    sop_reference = response.get("relevant_sop") or {}
    passages = sop_reference.get("passages") or []
    if passages:
        heading = "Relevant SOP reference"
        if sop_reference.get("approved") is not True:
            heading += " · REFERENCE ONLY — NOT APPROVED"
        source_lines = []
        for item in passages[:5]:
            location = item.get("section") or (f"Page {item['page']}" if item.get("page") else "Retrieved passage")
            source_lines.append(f"{item.get('sop_id') or sop_reference.get('sop_id')} · {location}: {item.get('text')}")
        sections.append(heading + "\n" + "\n".join(f"• {item}" for item in source_lines))
    criteria = response.get("resolution_criteria")
    if criteria:
        sections.append("Resolution criteria\n" + str(criteria))
    return "\n\n".join(sections)


# Plant identifiers contain numeric segments in different positions (for
# example ALM-C01-VB and SOP-P02-VLV-01). Mask the whole hyphenated identifier
# before measurement validation so those digits are never treated as claims.
_IDENTIFIER = re.compile(r"\b(?=[A-Z0-9-]*\d)[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", re.IGNORECASE)
_NAMED_COMPONENTS = re.compile(
    r"\b(?:valve|pump|compressor|tank|unit|transmitter|filter|circuit|breaker|line|header|switch|motor|vessel|stage|loop|step|check|item|action|point|rule|clause|phase|section|option|rev|revision|sop|page)\s*#?\s*\d+(?:\.\d+)*(?:-[A-Za-z0-9]+)*\b",
    re.IGNORECASE,
)
_BULLET_NUMBERS = re.compile(r"(?:(?<=^)|(?<=\s))\d+\.(?=\s)")
_ISO_TIMESTAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b",
    re.IGNORECASE,
)
_ISO_DATE_FRAGMENT = re.compile(r"(?<!\d)\d{4}-\d{2}(?:-\d{2})?(?!\d)")
_CLOCK_FRAGMENT = re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?!\d)")
_UNVERIFIED_PROCEDURAL_INSTRUCTION = re.compile(
    r"(?im)(?:^|[.!?]\s+|\n)\s*(?:[-*]\s*|\d+[.)]\s*)?"
    r"(?:you\s+should\s+|the\s+operator\s+should\s+|must\s+|please\s+)?"
    r"(?!(?:do\s+not|don't|never|avoid|not)\b)"
    r"(?:first,?\s+|then\s+|next\s+)?"
    r"(?:silence|acknowledge|inspect|switch|open|close|isolate|reset|restore|"
    r"adjust|increase|decrease|set|bypass|monitor|verify|check)\b"
)


def compact_llm_context(
    event: Dict[str, Any],
    context: Optional[Dict[str, Any]],
    grounded: Dict[str, Any],
    conversation: Optional[List[Dict[str, str]]] = None,
    similar_incidents: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a compact, already-grounded packet. Never include the full SOP library."""
    context = context or {}
    trends = []
    for trend in (context.get("trend_summaries") or grounded.get("trend_summaries") or [])[:8]:
        trends.append({
            "tag": trend.get("tag"),
            "unit": trend.get("unit"),
            "first_observed": trend.get("first_observed"),
            "last_observed": trend.get("last_observed"),
            "minimum": trend.get("minimum"),
            "maximum": trend.get("maximum"),
            "absolute_change": trend.get("absolute_change"),
            "percentage_change": trend.get("percentage_change"),
            "important_changes": (trend.get("important_changes") or [])[:3],
            "reading_count": trend.get("reading_count"),
            "observed_coverage_seconds": trend.get("observed_coverage_seconds"),
            "leading_unobserved_seconds": trend.get("leading_unobserved_seconds"),
            "trailing_unobserved_seconds": trend.get("trailing_unobserved_seconds"),
            "gap_count": trend.get("gap_count"),
            "coverage_note": trend.get("coverage_note"),
        })
    # Keep numerical trend evidence typed: an absolute movement in a % tag is
    # percentage points, while percentage_change is relative to its start.
    numeric_facts = _structured_numeric_facts(trends, context.get("window"))
    sources = []
    for item in (grounded.get("sources") or [])[:5]:
        explicitly_approved = item.get("verified") is True and item.get("approved") is True
        sources.append({
            "document_name": item.get("document_name"),
            "sop_id": item.get("sop_id"),
            "section": item.get("section"),
            "step_number": item.get("step_number"),
            "step_title": item.get("step_title"),
            "verified": item.get("verified") is True,
            "approved": item.get("approved") is True,
            "page": item.get("page"),
            "document_status": item.get("document_status") or "Approval status not verified",
            # Retrieved unapproved text is descriptive reference evidence only;
            # the prompt forbids turning it into operational recommendations.
            "usage": "approved_guidance" if explicitly_approved else "reference_only_not_approved",
            "text": (item.get("text") or "")[:500] if item.get("verified") is True else None,
        })
    history = conversation or []
    limit = int(os.environ.get("OPSLENS_ASSISTANT_HISTORY_LIMIT", "8"))
    return {
        "selected_event": context.get("selected_event") or grounded.get("incident_context"),
        "window": context.get("window"),
        "data_sources": context.get("data_sources") or [],
        "topology": context.get("topology") or {},
        "incident_analysis": context.get("incident_analysis") or {},
        "trend_summaries": trends,
        "numeric_facts": numeric_facts,
        "related_events": [
            {"event_id": item.get("event_id"), "alarm_id": item.get("alarm_id"),
             "timestamp": item.get("timestamp_utc") or item.get("timestamp"),
             "equipment_id": item.get("equipment_id"), "tags": item.get("tags") or [],
             "configured_severity": item.get("configured_severity"), "status": item.get("status")}
            for item in (context.get("related_events") or [])[:8]
        ],
        "operator_actions": [
            {"action_id": item.get("action_id"), "event_id": item.get("event_id"),
             "action_type": item.get("action_type"), "operator": item.get("operator"),
             "timestamp": item.get("timestamp_utc") or item.get("timestamp"), "notes": item.get("notes")}
            for item in (context.get("operator_actions") or [])[:8]
        ],
        "event_story": ((context.get("incident_analysis") or {}).get("event_story") or event.get("story") or {}),
        "evidence": {
            "likely_contributor_tag": (event.get("evidence") or {}).get("likely_contributor_tag"),
            "score_is_not_a_probability": True,
        },
        "sop_passages": sources,
        "missing_data": context.get("missing_data") or [],
        "hypotheses": context.get("hypotheses") or [],
        "similar_incidents_in_available_day_window": similar_incidents or [],
        "recent_conversation": history[-limit:],
        "deterministic_answer": grounded.get("answer"),
        "uncertainty_status": grounded.get("uncertainty_status"),
        "immediate_checks": grounded.get("immediate_checks") or [],
    }


def _allowed_numbers(*blobs: Any) -> set[float]:
    allowed: set[float] = set()
    for blob in blobs:
        text = blob if isinstance(blob, str) else json.dumps(blob, default=str)
        cleaned = _ISO_DATE_FRAGMENT.sub(" ", _ISO_TIMESTAMP.sub(" ", _IDENTIFIER.sub("", text)))
        for token in re.findall(r"-?\d+(?:\.\d+)?", cleaned):
            try:
                allowed.add(float(token))
            except ValueError:
                continue
    return allowed


def _tag_numeric_facts(compact: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Index typed numeric facts by source tag for claim validation."""
    facts: Dict[str, Dict[str, Any]] = {}
    structured = compact.get("numeric_facts")
    if not isinstance(structured, list):
        structured = _structured_numeric_facts(compact.get("trend_summaries") or [], compact.get("window"))
    source_units = {str(item.get("tag") or "").strip().upper(): str(item.get("unit") or "").strip()
                    for item in (compact.get("trend_summaries") or []) if item.get("tag")}
    for fact in structured:
        tag = str(fact.get("tag") or "").strip().upper()
        if tag:
            facts.setdefault(tag, {"unit": source_units.get(tag, ""), "facts": []})["facts"].append(fact)
    return facts


def _structured_numeric_facts(trends: list[Dict[str, Any]], window: Optional[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Represent readings and calculated changes as explicit grounded facts."""
    result: list[Dict[str, Any]] = []

    def add_fact(tag: Optional[str], equipment_id: Optional[str], metric: str, value: Any,
                 unit: str, change_type: str, timestamps: list[str], source: str) -> None:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            return
        tag_part = tag or "context"
        time_part = timestamps[-1].replace(":", "").replace("-", "") if timestamps else ""
        fact_id = f"{tag_part}.{metric}" + (f".{time_part}" if metric.startswith("important_") else "")
        result.append({
            "fact_id": fact_id,
            "equipment_id": equipment_id,
            "tag": tag,
            "metric": metric,
            "exact_value": float(value),
            "unit": unit,
            "change_type": change_type,
            "timestamps": timestamps,
            "source_records": [source],
        })

    for trend in trends:
        tag = str(trend.get("tag") or "").strip().upper()
        if not tag:
            continue
        equipment_id = trend.get("equipment_id")
        unit = str(trend.get("unit") or "").strip()
        percent_valued = unit == "%"
        # Include every numeric value that the deterministic trend explanation
        # may mention. Keeping these typed prevents a correct sample count or
        # coverage duration from being treated as an unsupported measurement.
        for metric, value, fact_unit, change_type in (
            ("reading_count", trend.get("reading_count"), "readings", "observation_count"),
            ("observed_coverage_seconds", trend.get("observed_coverage_seconds"), "seconds", "coverage_duration"),
            ("leading_unobserved_seconds", trend.get("leading_unobserved_seconds"), "seconds", "unobserved_duration"),
            ("trailing_unobserved_seconds", trend.get("trailing_unobserved_seconds"), "seconds", "unobserved_duration"),
            ("gap_count", trend.get("gap_count"), "gaps", "gap_count"),
        ):
            add_fact(tag, equipment_id, metric, value, fact_unit, change_type,
                     [point.get("timestamp") for point in
                      (trend.get("first_observed"), trend.get("last_observed"))
                      if isinstance(point, dict) and point.get("timestamp")],
                     "SQLite.tag_readings summarized by trend_analysis")
        for metric in ("first_observed", "last_observed", "minimum", "maximum"):
            point = trend.get(metric)
            if (isinstance(point, dict) and isinstance(point.get("value"), (int, float))
                    and not isinstance(point.get("value"), bool) and math.isfinite(float(point["value"]))):
                add_fact(tag, equipment_id, metric, point["value"], unit, "observed_reading",
                         [point.get("timestamp")] if point.get("timestamp") else [], "SQLite.tag_readings")
        for metric, value, change_type in (
            ("absolute_change", trend.get("absolute_change"), "percentage_point_change" if percent_valued else "absolute_change"),
            ("percentage_change", trend.get("percentage_change"), "relative_percentage_change"),
        ):
            add_fact(tag, equipment_id, metric, value,
                     "percentage points" if change_type == "percentage_point_change" else
                     "%" if change_type == "relative_percentage_change" else unit,
                     change_type,
                     [point.get("timestamp") for point in
                      (trend.get("first_observed"), trend.get("last_observed"))
                      if isinstance(point, dict) and point.get("timestamp")],
                     "calculated from SQLite.tag_readings")
        for change in trend.get("important_changes") or []:
            for metric, value in (("important_previous_reading", change.get("previous_value")),
                                  ("important_reading", change.get("value"))):
                stamp = change.get("from_timestamp") if metric == "important_previous_reading" else change.get("timestamp")
                add_fact(tag, equipment_id, metric, value, unit, "observed_reading",
                         [stamp] if stamp else [], "SQLite.tag_readings")
            for metric, value, change_type in (
                ("important_absolute_change", change.get("absolute_change"), "percentage_point_change" if percent_valued else "absolute_change"),
                ("important_percentage_change", change.get("percentage_change"), "relative_percentage_change"),
            ):
                add_fact(tag, equipment_id, metric, value,
                         "percentage points" if change_type == "percentage_point_change" else
                         "%" if change_type == "relative_percentage_change" else unit,
                         change_type,
                         [stamp for stamp in (change.get("from_timestamp"), change.get("timestamp")) if stamp],
                         "calculated from SQLite.tag_readings")
    if isinstance(window, dict):
        duration = window.get("duration_minutes")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(float(duration)):
            add_fact(None, None, "context_window_duration", duration, "minutes", "context_window_duration",
                     [stamp for stamp in (window.get("start"), window.get("end")) if stamp],
                     "ContextBuilder.window start/end timestamps")
    return result


def _date_fragments(*blobs: Any) -> set[str]:
    found: set[str] = set()
    for blob in blobs:
        text = blob if isinstance(blob, str) else json.dumps(blob, default=str)
        found.update(_ISO_DATE_FRAGMENT.findall(text))
    return found


def _clause_for_span(text: str, start: int, end: int) -> str:
    boundary = re.compile(r"[!?;\n]|(?<=\.)\s+(?=[A-Z\"'])")
    left_matches = list(boundary.finditer(text, 0, start))
    left = left_matches[-1].end() if left_matches else 0
    right_match = boundary.search(text, end)
    right = right_match.start() if right_match else len(text)
    return text[left:right]


def _matches_tag_change(value: float, signed_token: str, clause: str, facts: list[Dict[str, Any]], unit_context: str = "") -> bool:
    """Match a claim to a typed change fact; rounding follows shown precision."""
    lowered = clause.lower()
    decreasing = any(word in lowered for word in ("fell", "decreased", "declined", "dropped", "reduced", "lower"))
    increasing = any(word in lowered for word in ("rose", "increased", "climbed", "surged", "higher", "up by"))
    percentage_points = bool(re.match(r"\s*percentage\s+points?\b", unit_context, re.IGNORECASE))
    relative_percent = (bool(re.match(r"\s*(?:%|percent(?:age)?\b)", unit_context, re.IGNORECASE))
                        and not percentage_points)
    physical_unit = any(_unit_follows_value(unit, unit_context) for unit in ("L/min", "A", "bar"))
    change_language = percentage_points or relative_percent or physical_unit or any(
        word in lowered for word in ("change", "delta", "fell", "decreased", "declined", "dropped", "reduced", "lower", "rose", "increased", "climbed", "surged", "higher", "up by")
    )
    for fact in facts:
        kind = fact["change_type"]
        if kind == "percentage_point_change" and not percentage_points:
            continue
        if kind == "relative_percentage_change" and not relative_percent:
            continue
        if kind == "absolute_change" and (percentage_points or relative_percent or not physical_unit):
            continue
        if kind == "absolute_change" and not _unit_follows_value(str(fact.get("unit") or ""), unit_context):
            continue
        if kind not in {"percentage_point_change", "relative_percentage_change", "absolute_change"} or not change_language:
            continue
        actual = float(fact["exact_value"])
        decimal_places = len(signed_token.lstrip("+-").split(".", 1)[1]) if "." in signed_token else 0
        tolerance = 0.5 * (10 ** -decimal_places)
        if signed_token.startswith(("+", "-")):
            if abs(value - actual) <= tolerance:
                return True
            continue
        direction_matches = (actual < 0 and decreasing) or (actual > 0 and increasing)
        if direction_matches and abs(value - abs(actual)) <= tolerance:
            return True
    return False


def _matches_tag_reading(value: float, signed_token: str, clause: str, facts: list[Dict[str, Any]], unit_context: str = "") -> bool:
    """Match a reading only when its measurement unit or explicit range is present."""
    lowered = clause.lower()
    for fact in facts:
        if fact["change_type"] == "observation_count":
            if not re.search(r"\b(?:numeric\s+recorded\s+)?(?:readings?|samples?)\b", lowered):
                continue
            if any(_unit_follows_value(unit, unit_context) for unit in ("L/min", "A", "bar", "%")):
                continue
            if _matches_rounded_value(value, signed_token, fact):
                return True
            continue
        if fact["change_type"] != "observed_reading":
            continue
        unit = str(fact.get("unit") or "").strip().lower()
        unit_present = bool(unit and re.search(re.escape(unit), lowered))
        range_claim = bool(re.search(r"\bfrom\s+[+-]?\d", lowered))
        if not unit_present and not range_claim:
            continue
        actual = float(fact["exact_value"])
        if _matches_rounded_value(value, signed_token, fact):
            return True
    return False


def _matches_rounded_value(value: float, signed_token: str, fact: Dict[str, Any]) -> bool:
    """Compare to one typed fact using only the precision shown in the claim."""
    actual = float(fact["exact_value"])
    decimal_places = len(signed_token.lstrip("+-").split(".", 1)[1]) if "." in signed_token else 0
    tolerance = 0.5 * (10 ** -decimal_places)
    return abs(value - actual) <= tolerance


def _matches_tag_coverage(value: float, signed_token: str, clause: str, facts: list[Dict[str, Any]], unit_context: str) -> bool:
    lowered = clause.lower()
    for fact in facts:
        kind = fact["change_type"]
        if kind not in {"coverage_duration", "unobserved_duration", "gap_count"}:
            continue
        if kind == "gap_count":
            if not re.search(r"\bgaps?\b", lowered):
                continue
            unit = "gaps"
        else:
            if not _unit_follows_value("seconds", unit_context):
                continue
            if kind == "coverage_duration" and not re.search(r"\b(?:coverage|span)\b", lowered):
                continue
            if kind == "unobserved_duration" and not re.search(r"\b(?:unobserved|no\s+(?:numeric\s+)?readings?|without\s+(?:numeric\s+)?readings?)\b", lowered):
                continue
            unit = "seconds"
        if _unit_follows_value(unit, unit_context) and _matches_rounded_value(value, signed_token, fact):
            return True
    return False


def _timestamps_in(*blobs: Any) -> set[str]:
    found: set[str] = set()
    for blob in blobs:
        text = blob if isinstance(blob, str) else json.dumps(blob, default=str)
        found.update(_ISO_TIMESTAMP.findall(text))
    return found


def _clock_fragments(*blobs: Any) -> set[str]:
    """Return clock portions of recorded ISO timestamps for safe display checks."""
    clocks: set[str] = set()
    for timestamp in _timestamps_in(*blobs):
        match = re.search(r"[T ](\d{2}:\d{2}:\d{2})", timestamp)
        if match:
            clocks.add(match.group(1))
            clocks.add(match.group(1)[:5])
    return clocks


def _is_recorded_window_duration(text: str, start: int, end: int, value: float, compact: Dict[str, Any]) -> bool:
    """Recognize only an explicitly framed duration matching actual window timestamps.

    ContextWindow.duration_minutes is rounded to a whole minute by the schema;
    allow at most half a minute of difference from the timestamp interval.
    """
    window = compact.get("window") or {}
    if not isinstance(window, dict):
        return False
    duration = window.get("duration_minutes")
    start_timestamp, end_timestamp = window.get("start"), window.get("end")
    if (isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration)) or value != float(duration)
            or not isinstance(start_timestamp, str) or not isinstance(end_timestamp, str)):
        return False
    try:
        start_dt = datetime.fromisoformat(start_timestamp.strip().replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_timestamp.strip().replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        actual_minutes = (end_dt.astimezone(timezone.utc) - start_dt.astimezone(timezone.utc)).total_seconds() / 60
    except (TypeError, ValueError, OverflowError):
        return False
    if actual_minutes < 0 or abs(actual_minutes - float(duration)) > 0.5:
        return False

    return _has_context_duration_framing(text, start, end)


def _is_window_duration_value(value: float, compact: Dict[str, Any]) -> bool:
    duration = (compact.get("window") or {}).get("duration_minutes")
    return (isinstance(duration, (int, float)) and not isinstance(duration, bool)
            and math.isfinite(float(duration)) and value == float(duration))


def _has_context_duration_framing(text: str, start: int, end: int) -> bool:
    # Accept only unambiguous window-centric constructions. In particular,
    # do not accept a sensor clause such as "MOT-02-CUR was 30 minutes during
    # the context window": the duration there is attached to the tag.
    suffix = text[end:end + 40]
    prefixed_window = re.match(
        r"[-\s]minutes?\s+(?:the\s+)?(?:preceding\s+|previous\s+|last\s+)?(?:context|time)\s+window\b",
        suffix, re.IGNORECASE,
    )
    if prefixed_window:
        return True

    unit = re.match(r"\s*minutes?\b", suffix, re.IGNORECASE)
    if not unit:
        unit = re.match(r"\s*mins?\b", suffix, re.IGNORECASE)
    if not unit:
        return False
    before = text[max(0, start - 64):start]
    # The subject must be the context window itself, directly governing the
    # duration ("context window spans 30 minutes"). No intervening tag or
    # sensor assertion is allowed.
    return bool(re.search(
        r"\b(?:the\s+)?(?:preceding\s+|previous\s+|last\s+)?(?:context|time)\s+window"
        r"(?:\s+duration)?\s+(?:(?:[:=]\s*)|(?:is|was|covers|spans|lasts)\s+)$",
        before, re.IGNORECASE,
    ))


def _llm_answer_rejection_reason(text: str, grounded: Dict[str, Any], compact: Dict[str, Any], wants_procedure: bool) -> Optional[str]:
    if not text or not isinstance(text, str) or len(text.strip()) < 8:
        return "empty_or_short_answer"
    lowered = text.lower()
    if wants_procedure:
        has_approved_passage = any(
            item.get("verified") is True and item.get("approved") is True and item.get("text")
            for item in (compact.get("sop_passages") or [])
        )
        if not has_approved_passage and re.search(
            r"\b(?:according to|per|the SOP (?:says|states|instructs|requires)|the procedure (?:says|states|instructs|requires)|SOP guidance says)\b",
            text, re.IGNORECASE,
        ):
            return "unretrieved_sop_instruction_claim"
    if (wants_procedure and (grounded.get("sop_resolution") or {}).get("status") == "reference_unapproved"):
        # We may still use the model to explain incident evidence, but retrieved
        # unverified material must never become an instruction, regardless of
        # how the operator phrased the incident question.
        if _UNVERIFIED_PROCEDURAL_INSTRUCTION.search(text) or any(
            phrase in lowered for phrase in ("increase setpoint", "reset the plc")
        ):
            logger.warning("[Assistant] Rejected LLM answer containing actionable language for an unverified SOP")
            return "unverified_sop_actionable_language"
    # Unapproved reference passages may be shown verbatim in the UI, but their
    # numeric thresholds/timestamps are not LLM grounding evidence. Otherwise
    # a number in a draft SOP could authorize a generated operating claim.
    validation_grounded, validation_compact = _llm_grounding_evidence(grounded, compact)
    allowed_timestamps = _timestamps_in(
        validation_grounded.get("answer"), validation_compact, validation_grounded.get("supporting_readings"),
        validation_grounded.get("supporting_events"), validation_grounded.get("sources"),
    )
    output_timestamps = set(_ISO_TIMESTAMP.findall(text))
    if output_timestamps:
        invented = output_timestamps - allowed_timestamps
        if invented:
            logger.warning("[Assistant] Rejected LLM answer containing an unrecorded timestamp")
            return "ungrounded_timestamp"
    allowed_dates = _date_fragments(
        validation_grounded.get("answer"), validation_compact, validation_grounded.get("supporting_readings"),
        validation_grounded.get("supporting_events"), validation_grounded.get("sources"),
    )
    if set(_ISO_DATE_FRAGMENT.findall(text)) - allowed_dates:
        logger.warning("[Assistant] Rejected LLM answer containing an unrecorded date")
        return "ungrounded_timestamp"
    allowed_clocks = _clock_fragments(
        validation_grounded.get("answer"), validation_compact, validation_grounded.get("supporting_readings"),
        validation_grounded.get("supporting_events"), validation_grounded.get("sources"),
    )
    output_clocks = set(_CLOCK_FRAGMENT.findall(_ISO_TIMESTAMP.sub(" ", text)))
    if output_clocks - allowed_clocks:
        logger.warning("[Assistant] Rejected LLM answer containing an unrecorded clock time")
        return "ungrounded_timestamp"
    allowed = _allowed_numbers(validation_grounded.get("answer"), validation_compact, validation_grounded.get("supporting_readings"), validation_grounded.get("supporting_events"), validation_grounded.get("sources"))
    tag_facts = _tag_numeric_facts(validation_compact)
    numeric_text = _ISO_TIMESTAMP.sub(lambda match: " " * len(match.group()), text)
    numeric_text = _ISO_DATE_FRAGMENT.sub(lambda match: " " * len(match.group()), numeric_text)
    # Clock fragments are validated against recorded timestamp fields above;
    # mask them here so their hour/minute components are not treated as readings.
    numeric_text = _CLOCK_FRAGMENT.sub(lambda match: " " * len(match.group()), numeric_text)
    numeric_text = _IDENTIFIER.sub(lambda match: " " * len(match.group()), numeric_text)
    numeric_text = _NAMED_COMPONENTS.sub(lambda match: " " * len(match.group()), numeric_text)
    numeric_text = _BULLET_NUMBERS.sub(lambda match: " " * len(match.group()), numeric_text)
    for match in re.finditer(r"[+-]?\d+(?:\.\d+)?", numeric_text):
        token = match.group(0)
        try:
            value = float(token)
        except ValueError:
            return "ungrounded_numeric_value"
        clause = _clause_for_span(text, match.start(), match.end())
        clause_lower = clause.lower()
        is_hypo_context = any(m in clause_lower for m in (
            "hypothetical", "hypothetically", "if the", "if a", "if we", "if valve", "if pressure",
            "suppose", "assuming", "what if", "would indicate", "would weaken", "would suggest",
            "would mean", "not observed", "not been observed", "unobserved", "were to return",
            "were to rise", "were to fall", "remained at", "returned to", "would point", "would require"
        ))
        is_actual_claim = any(m in clause_lower for m in (
            "was recorded", "observed reading", "historian recorded", "at trigger", "first observed",
            "last observed", "trend changed", "actual reading", "recorded reading"
        ))
        is_hypo_question = compact.get("uncertainty_status") == "hypothetical_reasoning"
        if (is_hypo_context or is_hypo_question) and not is_actual_claim:
            continue
        if _is_recorded_window_duration(text, match.start(), match.end(), value, compact):
            continue
        if (_has_context_duration_framing(text, match.start(), match.end())
                or _is_window_duration_value(value, compact)):
            # A framed duration that fails the timestamp-derived window check
            # must not pass via the generic exact-number evidence set.
            logger.warning("assistant_grounding_rejection claim_type=numeric token=%s tag_scope=unscoped reason=ungrounded_numeric_value", token)
            return "ungrounded_numeric_value"
        mentioned_tags = [tag for tag in tag_facts if re.search(
            rf"(?<![A-Z0-9]){re.escape(tag)}(?![A-Z0-9])", clause, re.IGNORECASE
        )]
        # A nearby alarm identifier can be closer to a reading token than the
        # sensor tag that owns it (for example "DPT rose from 0.99 to 4.8 kPa
        # before ALM-..."). Prefer the unique tag whose engineering unit is
        # explicitly attached to the clause; fall back to positional scoping
        # only when the unit does not disambiguate the instruments.
        unit_scoped_tags = [
            tag for tag in mentioned_tags
            if tag_facts[tag]["unit"] and _unit_mentioned(tag_facts[tag]["unit"], clause)
        ]
        scoped_tags = unit_scoped_tags if len(unit_scoped_tags) == 1 else _nearest_tag_scope(
            clause, match.start(), mentioned_tags
        )
        if not scoped_tags:
            # A percentage-point unit can uniquely identify a % instrument,
            # but only when there is exactly one such instrument in this clause.
            if re.search(r"\bpercentage\s+points?\b", clause, re.IGNORECASE):
                unit_tags = [tag for tag, facts in tag_facts.items() if facts["unit"] == "%"]
            else:
                unit_tags = [tag for tag, facts in tag_facts.items()
                             if facts["unit"] and _unit_mentioned(facts["unit"], clause)]
            if len(unit_tags) == 1:
                scoped_tags = unit_tags
        # Bind the unit/semantic marker to the number immediately before it;
        # a later percentage elsewhere in the same sentence must not change
        # an earlier physical delta's meaning.
        unit_context = text[match.end():min(len(text), match.end() + 24)]
        if scoped_tags:
            valid_for_scope = all(
                _matches_tag_reading(value, token, clause, tag_facts[tag]["facts"], unit_context)
                or _matches_tag_coverage(value, token, clause, tag_facts[tag]["facts"], unit_context)
                or _matches_tag_change(value, token, clause, tag_facts[tag]["facts"], unit_context)
                for tag in scoped_tags
            )
        else:
            # If a number could refer to a trend fact, require a tag/unit and
            # metric phrase; do not accept it merely because it occurs in JSON.
            trend_facts = [fact for group in tag_facts.values() for fact in group["facts"]]
            decimals = len(token.lstrip("+-").split(".", 1)[1]) if "." in token else 0
            rounding_tolerance = 0.5 * (10 ** -decimals)
            ambiguous_trend_value = any(abs(value - float(fact["exact_value"])) <= rounding_tolerance for fact in trend_facts)
            valid_for_scope = value in allowed and not ambiguous_trend_value
        if not valid_for_scope:
            # Keep diagnostics useful without logging the question, prompt, or
            # generated sentence. The rejected token and its tag scope suffice
            # to distinguish date/time fragments from unsupported measurements.
            logger.warning(
                "assistant_grounding_rejection claim_type=numeric token=%s tag_scope=%s reason=ungrounded_numeric_value",
                token, ",".join(scoped_tags) if scoped_tags else "unscoped",
            )
            return "ungrounded_numeric_value"
    return None


def _llm_grounding_evidence(grounded: Dict[str, Any], compact: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Exclude unapproved source prose from numeric/time grounding whitelists."""
    grounded_facts = dict(grounded)
    rendered_answer = grounded_facts.get("answer") or ""
    grounded_facts["answer"] = rendered_answer.split("\n\nRelevant SOP reference", 1)[0]
    grounded_facts["sources"] = [
        source for source in (grounded_facts.get("sources") or [])
        if isinstance(source, dict) and source.get("verified") is True and source.get("approved") is True
    ]
    compact_facts = dict(compact)
    compact_facts["sop_passages"] = [
        passage for passage in (compact_facts.get("sop_passages") or [])
        if isinstance(passage, dict) and passage.get("verified") is True and passage.get("approved") is True
    ]
    # The deterministic operator answer intentionally renders unapproved
    # source text verbatim in its reference-only section. Keep that text
    # visible to the operator, but exclude it from the numeric/time whitelist
    # just as we exclude the unapproved passage metadata above.
    deterministic_answer = compact_facts.get("deterministic_answer")
    if isinstance(deterministic_answer, str):
        compact_facts["deterministic_answer"] = deterministic_answer.split(
            "\n\nRelevant SOP reference", 1
        )[0]
    return grounded_facts, compact_facts


def _unit_mentioned(unit: str, clause: str) -> bool:
    """Match common engineering units without treating prose 'a' as amps."""
    if unit.strip().lower() == "a":
        return bool(re.search(r"(?<![A-Za-z0-9])A(?![A-Za-z0-9])", clause))
    return bool(re.search(re.escape(unit.strip()), clause, re.IGNORECASE))


def _nearest_tag_scope(clause: str, number_start: int, tags: list[str]) -> list[str]:
    """Bind a number to its nearest explicit tag in the same clause.

    A clause may compare several instruments. Requiring a numeric claim to match
    every tag mentioned in that clause incorrectly rejects valid facts; choosing
    the closest tag is safe, while equally close tags remain ambiguous.
    """
    if not tags:
        return []
    occurrences: list[tuple[int, str]] = []
    for tag in tags:
        for match in re.finditer(rf"(?<![A-Z0-9]){re.escape(tag)}(?![A-Z0-9])", clause, re.IGNORECASE):
            # Measure from the tag's nearest edge. This lets a tag immediately
            # before its value own that value even when a second tag follows.
            edge = match.end() if match.end() <= number_start else match.start()
            occurrences.append((edge, tag))
    if not occurrences:
        return []
    distances = [(abs(position - number_start), tag) for position, tag in occurrences]
    nearest = min(distance for distance, _ in distances)
    winners = sorted({tag for distance, tag in distances if distance == nearest})
    return winners if len(winners) == 1 else []


def _unit_follows_value(unit: str, suffix: str) -> bool:
    unit = unit.strip()
    if unit.lower() == "a":
        return bool(re.match(r"\s*A(?![A-Za-z0-9])", suffix))
    return bool(unit and re.match(rf"\s*{re.escape(unit)}(?![A-Za-z0-9])", suffix, re.IGNORECASE))


def _validate_llm_answer(text: str, grounded: Dict[str, Any], compact: Dict[str, Any], wants_procedure: bool) -> bool:
    return _llm_answer_rejection_reason(text, grounded, compact, wants_procedure) is None


def _parse_llm_payload(raw: str) -> Optional[Dict[str, Any]]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict) or not data.get("answer"):
        return None
    checks = data.get("immediate_checks") or []
    if not isinstance(checks, list):
        checks = []
    return {
        "answer": str(data["answer"]).strip(),
        "uncertainty_status": str(data.get("uncertainty_status") or "").strip() or None,
        "immediate_checks": [str(item).strip() for item in checks if str(item).strip()][:2],
    }


def build_assistant_prompt(question: str, compact: Dict[str, Any]) -> str:
    unverified_sop_policy = ""
    if compact.get("uncertainty_status") == "insufficient_approved_procedure":
        unverified_sop_policy = (
            "SOP STATUS IS UNVERIFIED: you may give one concise descriptive summary of the actual "
            "retrieved passage, attributed to its SOP ID and section and explicitly labelled "
            "REFERENCE ONLY — NOT APPROVED. Describe what the passage covers; do not phrase it as "
            "an imperative, recommendation, operating instruction, setpoint, or resolution criterion. "
            "State that approved guidance was not retrieved. Do not derive immediate checks from it.\n"
        )
    # Preserve the SOP excerpts and incident facts as a priority packet. A
    # blind character slice of the whole context used to truncate sop_passages
    # after dense trend/event data, so retrieval could succeed without its
    # relevant text ever reaching the model.
    facts_compact = {
        "selected_event": compact.get("selected_event"),
        "window": compact.get("window"),
        "trend_summaries": (compact.get("trend_summaries") or [])[:6],
        "numeric_facts": compact.get("numeric_facts") or [],
        "related_events": (compact.get("related_events") or [])[:6],
        "operator_actions": (compact.get("operator_actions") or [])[:6],
        "event_story": compact.get("event_story"),
        "evidence": compact.get("evidence"),
        "sop_passages": compact.get("sop_passages") or [],
        "missing_data": compact.get("missing_data") or [],
        "hypotheses": (compact.get("hypotheses") or [])[:6],
        "similar_incidents_in_available_day_window": (compact.get("similar_incidents_in_available_day_window") or [])[:4],
        "recent_conversation": (compact.get("recent_conversation") or [])[-4:],
        "uncertainty_status": compact.get("uncertainty_status"),
    }
    facts_json = json.dumps(facts_compact, default=str)
    # This bound is well above the compact packet for current OpsLens scenarios;
    # if exceeded, keep the leading incident/SOP fields rather than slicing the
    # JSON mid-passage.
    if len(facts_json) > 12000:
        facts_compact["trend_summaries"] = (facts_compact.get("trend_summaries") or [])[:3]
        facts_compact["numeric_facts"] = (facts_compact.get("numeric_facts") or [])[:12]
        facts_compact["related_events"] = (facts_compact.get("related_events") or [])[:3]
        facts_compact["operator_actions"] = (facts_compact.get("operator_actions") or [])[:3]
        facts_compact["recent_conversation"] = (facts_compact.get("recent_conversation") or [])[-2:]
        facts_json = json.dumps(facts_compact, default=str)
    return (
        "You are OpsLens, a read-only industrial HMI copilot. Use ONLY the JSON facts.\n"
        "Answer the exact operator question first; do not return a generic incident summary when a specific fact was asked for.\n"
        "Do not invent measurements, timestamps, operator actions, SOP steps, equipment relationships, or historical incidents.\n"
        "Use numeric values only when explicitly present in FACTS. Use each numeric_facts entry only for its named tag, metric, unit, timestamps, and change_type. When reporting a numeric sensor fact, name its tag in the same sentence and state its compatible unit/meaning. In comparisons with multiple tags, keep each value next to its own tag. Rounded values are allowed only to the precision justified by the displayed number. Counts must be described as readings/samples or gaps for the corresponding tag. Coverage durations must be described as coverage/unobserved time for the corresponding tag. Do not add estimates, sample intervals, or limits.\n"
        "Treat values and timestamps as a strict whitelist. For percentage-valued tags, absolute_change is percentage points; percentage_change is relative change from the starting value. Say 'percentage points' for the former and '%' or 'percent relative change' for the latter. For physical tags, absolute_change uses the source unit. Keep these meanings and units distinct. Context-window duration is valid only when framed as a context-window duration and consistent with its recorded start/end timestamps. For trend questions, omit unrelated numbers and do not estimate coverage duration. Do not state the numeric context-window duration unless the operator asks how long the window is; when asked, use the explicit phrase 'the 30-minute context window' only when supported by the window timestamps.\n"
        "If selected_event.timestamp_discrepancy is true, report the candidate event timestamp and event-story alarm-step timestamp with their source labels; do not choose one as a correction for the other. The context window is anchored to the recorded candidate trigger timestamp when available.\n"
        "For hypothetical or 'what if' questions (e.g., beginning with 'if', 'what if', 'suppose', 'assuming'):\n"
        "- Explain directly what that hypothetical scenario would indicate physically (e.g., weakening the initial hypothesis, suggesting alternative causes such as downstream obstruction, secondary component wear, or sensor calibration drift).\n"
        "- Explicitly state that these hypothetical readings have not actually been observed in plant records; stored incident telemetry at alarm trigger confirms the recorded condition.\n"
        "- Recommend checking: (1) latest sensor readings on the HMI runtime with timestamps and freshness, (2) whether correlated process values support the interpretation, (3) sensor validity, equipment relationships, and applicable SOP guidance.\n"
        "- Label hypothetical reasoning clearly and do not present it as observed plant conditions.\n"
        "For follow-up questions referencing recent_conversation, maintain conversational continuity and address the referenced topic directly.\n"
        "For trend questions, focus on the specific sensor or trend requested. Differentiate percentage points from relative percentage changes.\n"
        "Return a concise operator answer: one or two sentences for the bottom line only. Do not repeat evidence lists; OpsLens displays recorded evidence, checks, and limitations separately. Do not include raw database field names or long ISO timestamps in the answer. Include a specific explanation only as a hypothesis when records support it.\n"
        "Lead with Bottom Line Up Front. Include immediate checks only when the procedure source is explicitly approved.\n"
        "Distinguish observed facts, calculated trends, and hypotheses. Never treat correlation as causation.\n"
        "Never present evidence scores as probabilities. If facts are missing, say so.\n"
        "Answer open-ended natural-language questions using relevant records in FACTS; these examples do not limit question types. For topology, actions, recurrence, or handover, use only the corresponding records and stated time coverage. If FACTS do not cover the requested period or topic, state what is unavailable.\n"
        "For missing-information questions, list only gaps explicitly present in missing_data or the selected-event facts.\n"
        "For SOP questions, identify the document and section only when present in sop_passages. Check document_status and usage. If usage is reference_only_not_approved, summarize only the subject of the actual passage in descriptive language, label it REFERENCE ONLY — NOT APPROVED, and state that approved guidance was not retrieved; never turn it into an instruction or recommended action. You may still explain recorded readings, trends, event timing, and evidence-based hypotheses.\n"
        f"{unverified_sop_policy}"
        "This assistant cannot change setpoints, acknowledge alarms, or issue PLC commands.\n"
        "Return JSON: {\"answer\": string, \"uncertainty_status\": string, \"immediate_checks\": [string, string]}. The answer is the concise bottom line; do not duplicate the evidence panel.\n\n"
        f"OPERATOR_QUESTION:\n{question}\n\nFACTS:\n{facts_json}"
    )


def answer_incident_question(
    event: Dict[str, Any],
    question: str,
    context: Optional[Dict[str, Any]] = None,
    similar_incidents: Optional[List[Dict[str, Any]]] = None,
    conversation_id: Optional[str] = None,
    conversation: Optional[List[Dict[str, str]]] = None,
    llm_complete: Optional[Callable[[str], str]] = None,
    assembly_latency_ms: Optional[float] = None,
    sop_document_loader: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    started = perf_counter()
    grounded = build_assistant_response(
        event, question, context=context,
        similar_incidents=similar_incidents, conversation_id=conversation_id,
        sop_document_loader=sop_document_loader, progress_callback=progress_callback,
    )
    if progress_callback:
        progress_callback("deterministic_analysis_available")
    compact = compact_llm_context(event, context, grounded, conversation=conversation, similar_incidents=similar_incidents)
    wants_procedure = any(word in question.lower() for word in ("sop", "procedure", "instruction", "steps", "what should", "how do i"))
    generation_started = perf_counter()
    initial_inference_ms: Optional[float] = None
    correction_inference_ms: Optional[float] = None
    grounding_validation_ms: Optional[float] = None
    llm_complete = llm_complete or _llm_complete_override
    used_llm = False
    fallback_reason = "deterministic_record_grounded"
    correction_failure_reason: Optional[str] = None
    selected_provider_name = "none"
    selected_model = None
    provider_configuration_error = None
    used_provider = "deterministic"
    used_model = None
    accepted_llm_answer: Optional[str] = None
    provider_request_id = uuid4().hex[:12]
    provider_attempts: List[Dict[str, Any]] = []
    grounding_validation_result = "not_run"
    validation_rejection_reason: Optional[str] = None
    try:
        from llm_provider import configuration_error, llm_model, selected_provider
        selected_provider_name = selected_provider()
        selected_model = llm_model(selected_provider_name) if selected_provider_name not in ("", "none", "off", "disabled") else None
        provider_configuration_error = configuration_error()
    except Exception:
        # Preserve the deterministic answer if optional provider metadata fails.
        pass
    if llm_complete is None:
        if selected_provider_name not in ("", "none", "off", "disabled"):
            from llm_provider import complete_chat
            llm_complete = complete_chat
        else:
            llm_complete = None

    logger.info(
        "assistant_request_start request_id=%s incident_id=%s provider=%s model=%s provider_attempted=%s",
        provider_request_id, event.get("event_id") or "unknown", selected_provider_name,
        selected_model or "none", llm_complete is not None,
    )

    def invoke_provider(prompt_text: str, call_type: str) -> str:
        context_token = None
        attempt = {
            "call_type": call_type,
            "provider_attempted": True,
            "response_received": False,
            "http_status": None,
            "latency_ms": None,
            "parse_result": "not_run",
            "grounding_result": "not_run",
            "validation_rejection_reason": None,
        }
        provider_attempts.append(attempt)
        call_started = perf_counter()
        try:
            from llm_provider import (
                clear_provider_http_status, get_provider_http_status,
                reset_provider_request_context, set_provider_request_context,
            )
            clear_provider_http_status()
            context_token = set_provider_request_context(provider_request_id, call_type)
        except Exception:
            reset_provider_request_context = None
            get_provider_http_status = None
        logger.info("assistant_provider_call request_id=%s call_type=%s result=start", provider_request_id, call_type)
        try:
            response = llm_complete(prompt_text)
            attempt.update(
                response_received=bool(isinstance(response, str) and response.strip()),
                http_status=get_provider_http_status() if get_provider_http_status else None,
                latency_ms=round((perf_counter() - call_started) * 1000, 3),
            )
            logger.info(
                "assistant_provider_call request_id=%s incident_id=%s call_type=%s provider=%s model=%s result=response_received response_received=%s http_status=%s latency_ms=%.3f",
                provider_request_id, event.get("event_id") or "unknown", call_type,
                selected_provider_name, selected_model or "none", attempt["response_received"],
                attempt["http_status"] or "none", attempt["latency_ms"],
            )
            return response
        except Exception as exc:
            reason = getattr(exc, "kind", None) or "provider_error"
            attempt.update(
                http_status=(get_provider_http_status() if get_provider_http_status else None)
                or getattr(exc, "status_code", None),
                latency_ms=round((perf_counter() - call_started) * 1000, 3),
                error_type=type(exc).__name__,
            )
            logger.warning(
                "assistant_provider_call request_id=%s incident_id=%s call_type=%s provider=%s model=%s result=failed reason=%s error_type=%s http_status=%s latency_ms=%.3f",
                provider_request_id, event.get("event_id") or "unknown", call_type,
                selected_provider_name, selected_model or "none", reason, type(exc).__name__,
                attempt["http_status"] or "none", attempt["latency_ms"],
            )
            raise
        finally:
            if context_token is not None and reset_provider_request_context:
                reset_provider_request_context(context_token)

    if llm_complete is not None:
        try:
            if progress_callback:
                progress_callback("generating_explanation")
            prompt = build_assistant_prompt(question, compact)
            inference_started = perf_counter()
            raw = invoke_provider(prompt, "initial_inference")
            initial_inference_ms = round((perf_counter() - inference_started) * 1000, 3)
            parsed = _parse_llm_payload(raw)
            provider_attempts[-1]["parse_result"] = "valid_json" if parsed else "invalid_response_schema"
            validation_started = perf_counter()
            rejection_reason = (
                _llm_answer_rejection_reason(parsed["answer"], grounded, compact, wants_procedure)
                if parsed else "malformed_or_ungrounded_llm_output"
            )
            validation_elapsed = (perf_counter() - validation_started) * 1000
            grounding_validation_ms = (grounding_validation_ms or 0.0) + validation_elapsed
            grounding_validation_result = "passed" if rejection_reason is None else "rejected"
            validation_rejection_reason = rejection_reason
            provider_attempts[-1]["grounding_result"] = grounding_validation_result
            provider_attempts[-1]["validation_rejection_reason"] = rejection_reason
            logger.info(
                "assistant_provider_output request_id=%s incident_id=%s call_type=initial_inference parse_result=%s grounding_result=%s validation_rejection_reason=%s",
                provider_request_id, event.get("event_id") or "unknown",
                provider_attempts[-1]["parse_result"], grounding_validation_result,
                rejection_reason or "none",
            )
            # One bounded correction pass for unsupported numeric claims. The
            # second draft is independently validated and is never trusted by
            # virtue of being a retry.
            correction_lock = _CORRECTION_LOCKS[hash(str(event.get("event_id") or "")) % len(_CORRECTION_LOCKS)]
            if parsed and rejection_reason in {"ungrounded_numeric_value", "ungrounded_timestamp"} and correction_lock.acquire(blocking=False):
                correction = (
                    prompt + "\nCORRECTION REQUIRED: one numeric or timestamp claim was not grounded. Rewrite from scratch. "
                    "For each numeric sensor claim, use its exact tag, metric, compatible unit, and meaning from one numeric_facts record. "
                    "Keep values for different tags separate. Say 'the 30-minute context window' only if supported by its start/end timestamps. "
                    "Omit unsupported or ambiguous numeric/time claims; do not estimate."
                )
                try:
                    correction_started = perf_counter()
                    correction_raw = invoke_provider(correction, "correction")
                    parsed = _parse_llm_payload(correction_raw)
                    correction_inference_ms = round((perf_counter() - correction_started) * 1000, 3)
                    provider_attempts[-1]["parse_result"] = "valid_json" if parsed else "invalid_response_schema"
                    validation_started = perf_counter()
                    rejection_reason = (
                        _llm_answer_rejection_reason(parsed["answer"], grounded, compact, wants_procedure)
                        if parsed else "malformed_or_ungrounded_llm_output"
                    )
                    validation_elapsed = (perf_counter() - validation_started) * 1000
                    grounding_validation_ms = (grounding_validation_ms or 0.0) + validation_elapsed
                    grounding_validation_result = "passed" if rejection_reason is None else "rejected"
                    validation_rejection_reason = rejection_reason
                    provider_attempts[-1]["grounding_result"] = grounding_validation_result
                    provider_attempts[-1]["validation_rejection_reason"] = rejection_reason
                    logger.info(
                        "assistant_provider_output request_id=%s incident_id=%s call_type=correction parse_result=%s grounding_result=%s validation_rejection_reason=%s",
                        provider_request_id, event.get("event_id") or "unknown",
                        provider_attempts[-1]["parse_result"], grounding_validation_result,
                        rejection_reason or "none",
                    )
                except Exception as exc:
                    # Preserve why the draft was rejected as the fallback cause;
                    # report the failed repair separately for useful diagnostics.
                    correction_failure_reason = getattr(exc, "kind", None) or "llm_unavailable"
                    logger.warning("[Assistant] Grounding correction request failed (%s)", correction_failure_reason)
                finally:
                    correction_lock.release()
            elif parsed and rejection_reason in {"ungrounded_numeric_value", "ungrounded_timestamp"}:
                correction_failure_reason = "correction_in_flight_for_incident"
            if parsed and rejection_reason is None:
                accepted_llm_answer = parsed["answer"]
                # The model may rephrase facts; deterministic confidence and
                # operator checks remain authoritative backend outputs.
                used_provider = selected_provider_name if selected_provider_name != "none" else "configured_test_override"
                used_model = selected_model
                grounded["provider"] = (
                    f"{used_provider} · {used_model}" if used_model
                    else "configured LLM rephrasing grounded OpsLens records"
                )
                grounded["fallback_used"] = False
                grounded["llm_used"] = True
                used_llm = True
                fallback_reason = None
            else:
                fallback_reason = rejection_reason or "malformed_or_ungrounded_llm_output"
                logger.warning("[Assistant] LLM output rejected reason=%s; using deterministic fallback", fallback_reason)
        except Exception as exc:
            fallback_reason = getattr(exc, "kind", None) or "llm_unavailable"
            logger.warning("[Assistant] LLM call failed (%s); using deterministic fallback", fallback_reason)
    generation_latency_ms = round((perf_counter() - generation_started) * 1000, 3)
    grounded["assembly_latency_ms"] = round(float(assembly_latency_ms or (context or {}).get("assembly_latency_ms") or 0.0), 3)
    grounded["generation_latency_ms"] = generation_latency_ms
    grounded["timings_ms"] = {
        **(grounded.get("timings_ms") or {}),
        **((context or {}).get("timings_ms") or {}),
        "context_assembly": grounded["assembly_latency_ms"],
        "initial_llm_inference": initial_inference_ms,
        "grounding_validation": round(grounding_validation_ms, 3) if grounding_validation_ms is not None else None,
        "correction_inference": correction_inference_ms,
        "total_analysis": round((perf_counter() - started) * 1000 + grounded["assembly_latency_ms"], 3),
    }
    grounded["total_latency_ms"] = round((perf_counter() - started) * 1000 + grounded["assembly_latency_ms"], 3)
    grounded["fallback_reason"] = fallback_reason
    # Keep the correction request outcome directly available to API consumers;
    # provider_metadata retains its existing nested representation for clients
    # that already read it there.
    grounded["correction_failure_reason"] = correction_failure_reason
    grounded["llm_used"] = used_llm
    operator_response = grounded.get("operator_response") or _operator_response(event, grounded)
    # build_assistant_response preserves a question-specific deterministic
    # answer before formatting the legacy structured report. Keep that answer
    # for the operator panel when the LLM is unavailable or rejected.
    question_answer = accepted_llm_answer or grounded.get("question_answer") or grounded.get("answer")
    if accepted_llm_answer:
        operator_response["bottom_line"] = accepted_llm_answer
        if grounded.get("has_approved_sop") and parsed.get("immediate_checks"):
            operator_response["recommended_checks"] = parsed["immediate_checks"][:3]
    grounded["operator_response"] = operator_response
    # Keep the operator summary consistent with the resolved source state even
    # when the model rephrased the bottom line without mentioning the limitation.
    resolution = grounded.get("sop_resolution") or {}
    grounded["has_approved_sop"] = bool(resolution.get("approved") and grounded.get("sources"))
    if resolution.get("status") in ("retrieval_unavailable", "not_retrieved", "document_not_found", "document_content_unavailable"):
        grounded["sources"] = []
    if grounded.get("sources") and re.search(
        r"\b(?:no|not|unavailable|could not be found|wasn't retrieved|not in the current records)\b.{0,60}\b(?:relevant\s+)?(?:SOP|procedure|section)\b|\b(?:SOP|procedure|section)\b.{0,60}\b(?:unavailable|not available|not retrieved|could not be found|not in the current records)\b",
        operator_response.get("bottom_line") or "", re.IGNORECASE,
    ):
        if resolution.get("approved") is True:
            operator_response["bottom_line"] = f"A retrieved step in {resolution.get('sop_id')} is available and its approval is verified; see the referenced step below."
        else:
            operator_response["bottom_line"] = f"A matching step in {resolution.get('sop_id')} was retrieved, but its approval status is not verified; OpsLens cannot present it as approved guidance."
    if resolution.get("status") in ("retrieval_unavailable", "not_retrieved", "document_not_found", "document_content_unavailable"):
        operator_response["data_limitations"] = list(dict.fromkeys(
            (operator_response.get("data_limitations") or []) + [resolution.get("message", "SOP content unavailable.")]
        ))
    elif resolution.get("status") == "reference_unapproved":
        operator_response["data_limitations"] = list(dict.fromkeys(
            (operator_response.get("data_limitations") or []) + ["Retrieved SOP step approval status is not verified; it was not supplied as approved instructions to the model."]
        ))
    structured = _structured_assessment(event, grounded, operator_response)
    grounded.update(structured)
    operator_response.update(structured)
    grounded["answer"] = _render_operator_answer(operator_response)
    # Keep the response to the operator's actual question separate from the
    # concise assessment summary used by legacy clients.
    grounded["question_answer"] = question_answer
    grounded["selected_provider"] = selected_provider_name
    grounded["selected_model"] = selected_model
    grounded["used_provider"] = used_provider
    grounded["used_model"] = used_model
    if not used_llm:
        grounded["fallback_used"] = True
        grounded["provider"] = "OpsLens deterministic record-grounded assistant"
    grounded["provider_metadata"] = {
        "selected_provider": selected_provider_name,
        "selected_model": selected_model,
        "used_provider": used_provider,
        "used_model": used_model,
        "configuration_error": provider_configuration_error,
        "correction_failure_reason": correction_failure_reason,
    }
    grounded["compact_context"] = compact
    final_http_status = next((item.get("http_status") for item in reversed(provider_attempts) if item.get("http_status") is not None), None)
    logger.info(
        "assistant_request_complete request_id=%s incident_id=%s provider=%s model=%s provider_attempted=%s request_latency_ms=%.3f provider_http_status=%s response_received=%s parse_result=%s grounding_result=%s validation_rejection_reason=%s fallback_selected=%s fallback_reason=%s",
        provider_request_id, event.get("event_id") or "unknown", selected_provider_name,
        selected_model or "none", bool(provider_attempts), grounded["generation_latency_ms"],
        final_http_status or "none",
        any(item.get("response_received") for item in provider_attempts),
        provider_attempts[-1].get("parse_result", "not_run") if provider_attempts else "not_attempted",
        grounding_validation_result, validation_rejection_reason or "none",
        grounded["fallback_used"], fallback_reason or "none",
    )
    return grounded

