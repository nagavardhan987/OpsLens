"""
OpsLens - Deterministic Fallback Template Generator (Component 8)

Generates contract-compliant Guidance deterministically from input facts when
the external LLM API is unavailable, times out, or fails.
Preserves supplied evidence details and avoids creating unsupported procedure steps.
"""

import re
from typing import List, Optional
from models import EventStory, Evidence, SopMatch, Guidance


def _clean_action_step(step_text: str) -> str:
    """Clean step text to ensure a concise imperative statement."""
    # Strip leading step numbers like '1. ', 'Step 1: ', '1) '
    cleaned = re.sub(r'^(?:step\s*\d+[:.]?|\d+[.:)]\s*)', '', step_text, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else step_text.strip()


def format_deltas_summary(evidence: Evidence) -> str:
    """Format supporting deltas into concise string preserving exact signs and numbers."""
    if not evidence.supporting_deltas:
        return ""
    parts = []
    for d in evidence.supporting_deltas[:3]:
        sign = "+" if d.delta_pct > 0 else ""
        parts.append(f"{d.tag} ({sign}{d.delta_pct:.1f}%)")
    return ", ".join(parts)


def generate_sop_guidance(
    story: EventStory,
    evidence: Evidence,
    sop_match: SopMatch
) -> Guidance:
    """
    Return only retrieved procedure steps; this deterministic path does not invent filler actions.
    """
    tag = evidence.likely_contributor_tag
    causal = story.causal_label
    deltas_summary = format_deltas_summary(evidence)

    if deltas_summary:
        explanation = f"{causal}. The evidence ranking selects {tag} as the leading contributor; supporting deviations: {deltas_summary}."
    else:
        explanation = "Operator verification required. Supporting deviations are unavailable."

    actions: List[str] = []
    # Prefer the numbered procedure steps copied verbatim from the SOP PDF.
    # Raw page text (purpose/scope/PPE tables) is not an operator action.
    try:
        from sop_steps import procedure_steps
        extracted = procedure_steps(sop_match.sop_id) if sop_match.retrieval_method == "bundled_pdf_section" else {"steps": []}
    except Exception:
        extracted = {"steps": []}
    for step in extracted.get("steps", [])[:3]:
        actions.append(f"{sop_match.sop_id} step {step['number']} (p.{step['page']}): {step['text']}")
    if not actions:
        for step in sop_match.steps:
            cleaned = _clean_action_step(step)
            if cleaned and cleaned not in actions:
                actions.append(cleaned)
            if len(actions) >= 3:
                break

    if not actions:
        return Guidance(
            event_id=evidence.event_id,
            explanation_text="Operator verification required. No usable procedure steps were retrieved.",
            next_best_actions=["Operator verification required."],
            cited_sop_id="NONE",
        )

    return Guidance(
        event_id=evidence.event_id,
        explanation_text=explanation,
        next_best_actions=actions[:3],
        cited_sop_id=sop_match.sop_id
    )


def generate_fallback_guidance(
    story: EventStory,
    evidence: Evidence,
    sop_match: Optional[SopMatch] = None
) -> Guidance:
    """
    Construct safe deterministic Guidance when no SOP is available or when LLM/SLM fails.
    """
    return Guidance(
        event_id=evidence.event_id,
        explanation_text="Operator verification required.",
        next_best_actions=["Operator verification required."] * 3,
        cited_sop_id="NONE"
    )
