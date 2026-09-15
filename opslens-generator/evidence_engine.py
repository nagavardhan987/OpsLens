"""
OpsLens - Evidence & Attribution Engine (Component 6)

Consumes CorrelatedEvent objects from Component 4 and determines root-cause attribution:
identifies the likely_contributor_tag, confidence_score, confidence_label (HIGH/MEDIUM/LOW),
and supporting_deltas using an explicit, inspectable mathematical formula.

SCORING FORMULA:
================
For each correlated deviation d in a CorrelatedEvent (excluding the primary alarm tag itself):

    score = (abs(d.deviation_pct) / 100) * severity_weight * (1 / (d.topology_distance + 1)) * (1.2 if d.precedes_primary else 0.8)

Where:
  - abs(d.deviation_pct) / 100: Normalized magnitude of excursion from baseline midpoint.
  - severity_weight: Tag importance / criticality from TagRegistryEntry in [0.0, 1.0].
  - 1 / (d.topology_distance + 1): Topological proximity weighting in causal DAG (0 hops = 1.0, 1 hop = 0.5, 2 hops = 0.333, 3 hops = 0.25).
  - (1.2 if d.precedes_primary else 0.8): Precedence boost: deviations chronologically preceding the primary trigger are amplified (+20%), while post-trigger deviations are discounted (-20%).

ATTRIBUTION & CONFIDENCE:
=========================
  - likely_contributor_tag = argmax(score) among candidate deviations
  - confidence_score = score_top / sum(scores)  (Dominance ratio in [0.0, 1.0])
  - confidence_label:
      * "HIGH"   if confidence_score > 0.60
      * "MEDIUM" if confidence_score > 0.35
      * "LOW"    otherwise

AUDITABILITY:
=============
Every evaluation generates an inspectable scoring_breakdown containing raw factor calculations
stored alongside the Evidence contract in SQLite table `evidence`.
"""

from typing import Dict, List, Optional, Any
from models import CorrelatedEvent, Evidence, SupportingDelta
from registry_loader import RegistryLoader, get_registry_loader
from database import Database


class EvidenceEngine:
    """
    Evidence and Root-Cause Attribution Engine for industrial plant incidents.
    Computes transparent contribution scores and normalized confidence ratios.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        registry_loader: Optional[RegistryLoader] = None
    ):
        self.db = db
        self.loader = registry_loader if registry_loader is not None else get_registry_loader()

    def compute_contribution_score(
        self,
        tag: str,
        deviation_pct: float,
        topology_distance: int,
        precedes_primary: bool
    ) -> Dict[str, Any]:
        """
        Compute the contribution score and inspectable breakdown for a single tag deviation.

        Formula:
            score = (abs(deviation_pct) / 100) * severity_weight * (1 / (topology_distance + 1)) * (1.2 if precedes_primary else 0.8)
        """
        entry = self.loader.get_tag(tag)
        severity_weight = entry.severity_weight

        dev_mag_factor = abs(deviation_pct) / 100.0
        topo_factor = 1.0 / (float(topology_distance) + 1.0)
        precedence_factor = 1.2 if precedes_primary else 0.8

        raw_score = dev_mag_factor * severity_weight * topo_factor * precedence_factor

        return {
            "tag": tag,
            "raw_score": round(raw_score, 6),
            "deviation_pct": round(deviation_pct, 2),
            "severity_weight": severity_weight,
            "topology_distance": topology_distance,
            "precedes_primary": precedes_primary,
            "formula_factors": {
                "deviation_magnitude_factor": round(dev_mag_factor, 6),
                "severity_weight": severity_weight,
                "topology_distance_factor": round(topo_factor, 6),
                "temporal_precedence_factor": precedence_factor
            }
        }

    def evaluate_event(
        self,
        correlated_event: CorrelatedEvent,
        persist: bool = True
    ) -> Evidence:
        """
        Evaluate a CorrelatedEvent to produce an Evidence record:
        1. Filters candidate deviations (excluding primary alarm tag).
        2. Computes contribution scores for each deviation.
        3. Identifies likely_contributor_tag (highest score).
        4. Calculates normalized confidence_score and assigns confidence_label.
        5. Formats supporting_deltas with up/down direction.
        6. Persists to SQLite table `evidence` with inspectable audit log.
        """
        primary_tag = correlated_event.primary_tag
        candidate_devs = [
            d for d in correlated_event.correlated_deviations
            if d.tag != primary_tag
        ]

        scoring_breakdown: Dict[str, Any] = {
            "event_id": correlated_event.event_id,
            "primary_tag": primary_tag,
            "formula": "(abs(deviation_pct) / 100) * severity_weight * (1 / (topology_distance + 1)) * (1.2 if precedes_primary else 0.8)",
            "tag_scores": {}
        }

        # Build supporting_deltas from all correlated deviations
        supporting_deltas: List[SupportingDelta] = []
        for d in correlated_event.correlated_deviations:
            direction = "up" if d.deviation_pct >= 0 else "down"
            supporting_deltas.append(
                SupportingDelta(
                    tag=d.tag,
                    delta_pct=round(d.deviation_pct, 2),
                    direction=direction
                )
            )

        # Handle edge case: no candidate deviations
        if not candidate_devs:
            evidence = Evidence(
                event_id=correlated_event.event_id,
                likely_contributor_tag=primary_tag,
                confidence_score=0.0,
                confidence_label="LOW",
                supporting_deltas=supporting_deltas
            )
            scoring_breakdown["total_score"] = 0.0
            scoring_breakdown["confidence_calculation"] = "No correlated deviations available; default LOW confidence."
            if persist and self.db:
                self.db.save_evidence(evidence, breakdown=scoring_breakdown)
            return evidence

        # Score each candidate deviation
        scores: Dict[str, float] = {}
        for d in candidate_devs:
            result = self.compute_contribution_score(
                tag=d.tag,
                deviation_pct=d.deviation_pct,
                topology_distance=d.topology_distance,
                precedes_primary=d.precedes_primary
            )
            scores[d.tag] = result["raw_score"]
            scoring_breakdown["tag_scores"][d.tag] = result

        total_score = sum(scores.values())
        scoring_breakdown["total_score"] = round(total_score, 6)

        # Find top contributor
        top_tag = max(scores, key=lambda t: scores[t])
        top_score = scores[top_tag]

        # Normalized confidence score
        if total_score > 1e-9:
            confidence_score = round(top_score / total_score, 4)
        else:
            confidence_score = 0.0
        confidence_score = min(max(confidence_score, 0.0), 1.0)

        # Confidence label assignment
        if confidence_score > 0.60:
            confidence_label = "HIGH"
        elif confidence_score > 0.35:
            confidence_label = "MEDIUM"
        else:
            confidence_label = "LOW"

        scoring_breakdown["confidence_calculation"] = {
            "top_contributor": top_tag,
            "top_score": top_score,
            "total_score": round(total_score, 6),
            "normalized_dominance_ratio": confidence_score,
            "assigned_label": confidence_label
        }

        evidence = Evidence(
            event_id=correlated_event.event_id,
            likely_contributor_tag=top_tag,
            confidence_score=confidence_score,
            confidence_label=confidence_label,
            supporting_deltas=supporting_deltas
        )

        if persist and self.db:
            self.db.save_evidence(evidence, breakdown=scoring_breakdown)

        return evidence
