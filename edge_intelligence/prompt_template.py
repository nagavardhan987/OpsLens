"""
OpsLens - Prompt Template for Guidance Generation (Component 8)

Assembles structured facts from EventStory, Evidence, and SopMatch into a strict,
anti-hallucination prompt. Explicitly instructs the LLM to use ONLY the supplied facts
and output valid JSON matching the Guidance schema.
"""

import json
from typing import Dict, Any, Optional
from models import EventStory, Evidence, SopMatch

SYSTEM_INSTRUCTION = (
    "Use ONLY the facts provided below. Do not invent, estimate, or alter any numeric values, "
    "tag names, or thresholds. Your job is explanation and phrasing only."
)


def build_facts_payload(
    story: EventStory,
    evidence: Evidence,
    sop_match: Optional[SopMatch] = None
) -> Dict[str, Any]:
    """Serialize facts from EventStory, Evidence, and SopMatch into a clean dictionary."""
    deltas = [
        {
            "tag": d.tag,
            "delta_pct": round(float(d.delta_pct), 2),
            "direction": d.direction
        }
        for d in evidence.supporting_deltas
    ]
    sop_id = (
        sop_match.sop_id
        if (sop_match and sop_match.sop_id and sop_match.sop_id not in ("UNKNOWN-SOP", "SOP-NONE", "NONE"))
        else "NONE"
    )
    sop_title = (
        sop_match.sop_title
        if (sop_match and sop_match.sop_title)
        else "No pre-approved SOP available"
    )
    sop_steps = list(sop_match.steps) if (sop_match and sop_match.steps) else []

    trace = sop_match.rag_trace if sop_match and sop_match.rag_trace else {}
    return {
        "event_id": evidence.event_id,
        "causal_label": story.causal_label,
        "likely_contributor_tag": evidence.likely_contributor_tag,
        "confidence_label": evidence.confidence_label,
        "confidence_score": round(float(evidence.confidence_score), 4),
        "supporting_deltas": deltas,
        "sop_available": bool(sop_steps and sop_id != "NONE"),
        "sop_id": sop_id,
        "sop_title": sop_title,
        "sop_steps": sop_steps,
        "incident_context": trace.get("process_context", {}),
        "contextual_query": sop_match.query_context if sop_match else None,
        "retrieved_qdrant_chunks": sop_match.retrieved_chunks if sop_match else []
    }


def build_guidance_prompt(
    story: EventStory,
    evidence: Evidence,
    sop_match: Optional[SopMatch] = None
) -> str:
    """
    Construct the complete LLM prompt containing the system instruction,
    structured JSON facts, and strict JSON output specification.
    """
    facts = build_facts_payload(story, evidence, sop_match)
    facts_json = json.dumps(facts, indent=2)
    sop_available = facts.get("sop_available", False)
    sop_id = facts.get("sop_id", "NONE")

    if sop_available:
        action_task = "3 short imperative action items derived from the provided sop_steps"
        sop_constraint = f"4. cited_sop_id must match '{sop_id}' exactly."
    else:
        action_task = "Operator verification required. Do not suggest actions unsupported by the supplied evidence."
        sop_constraint = "4. cited_sop_id must be 'NONE'."

    prompt = (
        f"{SYSTEM_INSTRUCTION}\n\n"
        "FACTS (JSON):\n"
        f"```json\n{facts_json}\n```\n\n"
        "TASK:\n"
        "Generate operator guidance strictly based on the above facts.\n"
        "Treat retrieved SOP chunks as the only procedure source. Current telemetry, synthesized alarm, event story, graph relationships, and evidence are the only incident facts. If evidence is insufficient, say exactly: Operator verification required. Do not create procedures, sensor values, limits, equipment states, or control actions.\n"
        "Output ONLY a raw, valid JSON object (no markdown, no extra commentary) matching this schema:\n"
        "{\n"
        '  "event_id": "<exact event_id from facts>",\n'
        '  "explanation_text": "<1-2 sentences explaining the incident, citing likely_contributor_tag, confidence_label, and supporting_deltas without modifying any numbers>",\n'
        f'  "next_best_actions": ["<{action_task} - item 1>", "<{action_task} - item 2>", "<{action_task} - item 3>"],\n'
        f'  "cited_sop_id": "{sop_id}"\n'
        "}\n\n"
        "CRITICAL CONSTRAINTS:\n"
        "1. explanation_text must be 1-2 concise sentences for an industrial plant operator.\n"
        "2. Do NOT change, round, or recalculate any numbers or percentages in supporting_deltas.\n"
        f"3. next_best_actions must contain exactly 3 short imperative action items ({action_task}). When evidence is insufficient, use 'Operator verification required.' for the explanation and all three actions.\n"
        f"{sop_constraint}"
    )
    return prompt
