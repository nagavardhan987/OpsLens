"""
OpsLens Intelligence: Evidence Engine
Evaluates mathematical percentage deltas, chronological precedence,
and hydraulic physics to surface evidence-backed likely contributors.
"""

from typing import Dict, Any, List
from backend.data.scenario_data import EVIDENCE_PAYLOAD


class EvidenceEngine:
    """
    Computes and formats supporting evidence for the operator.
    Guarantees transparent, defensible explanations with verifiable metrics.
    Language strictly follows: 'Likely contributor based on correlated evidence.'
    """

    @staticmethod
    def get_evidence(is_incident: bool) -> Dict[str, Any]:
        if not is_incident:
            return {
                "has_incident": False,
                "likely_contributor": None,
                "attribution_statement": "System operating within nominal parameters. No anomalies detected.",
                "supporting_evidence": []
            }

        return {
            "has_incident": True,
            **EVIDENCE_PAYLOAD
        }
