"""
OpsLens Intelligence: SOP Retriever Module
Retrieves relevant Standard Operating Procedures based on keyword matching
against incident context and correlated deviations.
Architecturally designed as the seam for a real Vector DB / RAG / Edge SLM layer.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from backend.data.scenario_data import SOP_HP_P02


class SOPRetriever:
    """
    SOP Retrieval Seam:
    For MVP: Keyword-based matching against local SOP database.
    Production Extension: Replaced by local embedding vector search (e.g., ChromaDB/FAISS)
    and Edge SLM reranking for industrial SOP corpora.
    """

    def __init__(self):
        self.sop_catalog: List[Dict[str, Any]] = [SOP_HP_P02]

    def retrieve(self, query_context: str) -> Optional[Dict[str, Any]]:
        """
        Matches incident tags against SOP keyword index.
        """
        query_terms = [t.strip().lower() for t in query_context.replace("-", " ").split()]

        best_match = None
        highest_score = 0

        for sop in self.sop_catalog:
            keywords = [k.lower() for k in sop.get("keywords", [])]
            # Match score based on keyword overlap
            score = sum(1 for kw in keywords if any(term in kw or kw in term for term in query_terms))
            if score > highest_score:
                highest_score = score
                best_match = sop

        return best_match if highest_score > 0 else (self.sop_catalog[0] if self.sop_catalog else None)

    @classmethod
    def get_for_incident(cls, is_incident: bool) -> Dict[str, Any]:
        if not is_incident:
            return {
                "has_sop": False,
                "message": "No active incident requiring emergency SOP execution.",
                "sop": None
            }

        retriever = cls()
        sop = retriever.retrieve("pump-02 high pressure valve restriction")

        return {
            "has_sop": True,
            "match_source": "Deterministic Keyword Index (Edge RAG Seam)",
            "sop": sop
        }
