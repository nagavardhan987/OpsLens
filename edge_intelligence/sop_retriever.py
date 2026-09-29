"""
OpsLens - SOP Retrieval Engine (Component 7) — Qdrant Edition

Replaces the NumPy embedding search with QdrantVectorStore.
Key improvements:
  1. CONTEXTUAL QUERY: Builds a rich natural-language query from the full
     incident context (equipment, alarm, symptoms, telemetry, event story,
     likely contributor). NOT just the tag name.
  2. QDRANT SEARCH: Calls QdrantVectorStore.search() which uses real cosine
     similarity via the Qdrant engine.
  3. CORRECT TERMINOLOGY: The raw similarity score is labeled semantic_similarity,
     NOT match%, confidence, or probability.
  4. RAG TRACE: Every retrieval event logs a full audit record (rag_trace)
     for the /api/debug/rag/{incident_id} endpoint.
  5. BM25 FALLBACK: If Qdrant is unavailable, falls back to BM25 keyword search.
  6. GROUNDING CHUNKS: Returns top-K retrieved chunks that are passed to the LLM.
"""
import json
import re
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from models import EventStory, Evidence, SopMatch
from database import Database
from embed_index import load_all_sops, SOP_DIR

logger = logging.getLogger("opslens.sop_retriever")

_EMBED_MODEL = None
_QDRANT_STORE = None
_BM25_INDEX = None
_BM25_SOPS = None

RAG_TRACE_STORE: Dict[str, Any] = {}   # event_id -> rag_trace dict


def get_embed_model():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        from sentence_transformers import SentenceTransformer
        try:
            _EMBED_MODEL = SentenceTransformer(os.environ.get("OPSLENS_EMBEDDING_MODEL", "all-MiniLM-L6-v2"), local_files_only=True)
        except Exception as exc:
            raise RuntimeError("all-MiniLM-L6-v2 must be available in the local SentenceTransformer cache for offline operation") from exc
    return _EMBED_MODEL


def get_qdrant_store():
    global _QDRANT_STORE
    if _QDRANT_STORE is None:
        from vector_store.qdrant_store import QdrantVectorStore
        _QDRANT_STORE = QdrantVectorStore()
        # Auto-ingest SOPs if Qdrant is empty
        if _QDRANT_STORE.count() == 0:
            logger.info("[SopRetriever] Qdrant is empty. Auto-ingesting SOPs...")
            from ingest_sops import ingest
            ingest(vector_store=_QDRANT_STORE)
    return _QDRANT_STORE


def get_bm25_fallback():
    global _BM25_INDEX, _BM25_SOPS
    if _BM25_INDEX is None:
        from embed_index import format_sop_for_indexing
        from rank_bm25 import BM25Okapi
        _BM25_SOPS = load_all_sops(SOP_DIR)
        corpus = [re.findall(r"[A-Za-z0-9_\-]+", format_sop_for_indexing(s).lower())
                  for s in _BM25_SOPS]
        _BM25_INDEX = BM25Okapi(corpus)
    return _BM25_INDEX, _BM25_SOPS


class SopRetriever:
    """
    SOP retrieval engine using Qdrant vector similarity search.
    Embedding model: all-MiniLM-L6-v2 (SentenceTransformer)
    Vector store: local Qdrant service (or persistent embedded Qdrant)
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db

    # ------------------------------------------------------------------
    # Contextual Query Builder
    # ------------------------------------------------------------------

    def build_contextual_query(
        self,
        story: Optional[EventStory] = None,
        evidence: Optional[Evidence] = None,
        primary_tag: Optional[str] = None,
        telemetry_snapshot: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Build a rich natural-language query from the full incident context.
        This is embedded and used for semantic search in Qdrant.
        NOT just the tag name.
        """
        parts = []

        # Equipment
        equipment = None
        if evidence and evidence.likely_contributor_tag:
            tag = evidence.likely_contributor_tag
            if "P02" in tag or "FLW" in tag or "VLV" in tag or "PIT" in tag or "MOT" in tag:
                equipment = "Pump-02"
            elif "CMP" in tag:
                equipment = "Compressor-01"
            elif "TNK" in tag:
                equipment = "Tank-01"
        if equipment:
            parts.append(f"Equipment: {equipment}")

        # Primary alarm / tag
        pt = primary_tag or (story.steps[-1].tag if story and story.steps else None)
        if pt:
            alarm = "ALM-P02-HP" if "P02" in pt or "PIT-02" in pt else pt
            parts.append(f"Alarm: {alarm} (primary signal: {pt})")

        # Causal label / event story summary
        if story and story.causal_label:
            parts.append(f"Event: {story.causal_label}")

        # Symptoms from event story steps
        if story and story.steps:
            symptoms = []
            for step in story.steps:
                symptoms.append(step.description)
            parts.append("Symptoms: " + "; ".join(symptoms))

        # Supporting evidence deltas
        if evidence and evidence.supporting_deltas:
            delta_strs = []
            for d in evidence.supporting_deltas:
                direction = "increased" if d.direction == "up" else "decreased"
                delta_strs.append(f"{d.tag} {direction} by {abs(d.delta_pct):.1f}%")
            parts.append("Telemetry changes: " + ", ".join(delta_strs))

        # Likely contributor
        if evidence and evidence.likely_contributor_tag:
            parts.append(f"Likely contributor: {evidence.likely_contributor_tag}")

        if telemetry_snapshot:
            if telemetry_snapshot.get("alarm"):
                alarm_context = telemetry_snapshot["alarm"]
                parts.append(f"Alarm: {alarm_context.get('alarm_id')} — {alarm_context.get('condition')} ({alarm_context.get('severity')})")
            if telemetry_snapshot.get("equipment"):
                parts.append(f"Equipment: {telemetry_snapshot['equipment']}")
            snapshots = telemetry_snapshot.get("telemetry", [])
            if snapshots:
                parts.append("Telemetry: " + "; ".join(
                    f"{x.get('tag')}={x.get('value')} {x.get('unit','')} (baseline {x.get('baseline', 'unknown')})" for x in snapshots))
            if telemetry_snapshot.get("event_sequence"):
                parts.append("Event story: " + " -> ".join(telemetry_snapshot["event_sequence"]))
            if telemetry_snapshot.get("observations"):
                parts.append("Time-series observations: " + "; ".join(telemetry_snapshot["observations"]))
            if telemetry_snapshot.get("graph_context"):
                parts.append("Knowledge graph: " + "; ".join(telemetry_snapshot["graph_context"]))

        return "\n".join(parts) if parts else (primary_tag or "industrial equipment anomaly")

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        story: Optional[EventStory] = None,
        evidence: Optional[Evidence] = None,
        primary_tag: Optional[str] = None,
        persist: bool = True,
        top_k: int = 5,
        telemetry_snapshot: Optional[Dict[str, Any]] = None,
    ) -> SopMatch:
        """
        Retrieve the most relevant SOP using Qdrant semantic search.
        Returns SopMatch with:
          - semantic_similarity: raw cosine score from Qdrant (0.0-1.0)
          - retrieval_method: "qdrant_vector_search" or "bm25"
          - embedding_model: "all-MiniLM-L6-v2"
          - query_context: the full contextual query that was embedded
          - retrieved_chunks: top-K chunks returned by Qdrant
          - why_retrieved: human-readable retrieval rationale
          - rag_trace: full audit record for debug endpoint
        """
        event_id = (story.event_id if story else
                    (evidence.event_id if evidence else "unknown-event"))

        query_context = self.build_contextual_query(story, evidence, primary_tag, telemetry_snapshot)
        timestamp = datetime.now(timezone.utc).isoformat()

        # Attempt Qdrant semantic search
        match = None
        retrieval_method = "qdrant_vector_search"
        candidates_log = []
        raw_similarity = 0.0
        retrieved_chunks = []
        query_embedding = None

        try:
            model = get_embed_model()
            query_embedding = model.encode([query_context], convert_to_numpy=True)[0]
            qdrant = get_qdrant_store()
            equipment_filter = telemetry_snapshot.get("equipment") if telemetry_snapshot else None
            results = qdrant.search(query_vector=query_embedding.tolist(), top_k=top_k,
                                    equipment_filter=equipment_filter,
                                    plant_area_filter=telemetry_snapshot.get("plant_area") if telemetry_snapshot else None)

            if not results:
                raise RuntimeError("Qdrant returned no SOP chunks")
            if results:
                # Group by sop_id, take best score per SOP
                sop_scores: Dict[str, float] = {}
                sop_chunks: Dict[str, List[Dict]] = {}
                for r in results:
                    sid = r.sop_id
                    if sid not in sop_scores or r.similarity > sop_scores[sid]:
                        sop_scores[sid] = r.similarity
                    sop_chunks.setdefault(sid, []).append(r.to_dict())
                    candidates_log.append({
                        "sop_id": sid,
                        "chunk_id": r.chunk_id,
                        "section": r.payload.get("section", ""),
                        "similarity": r.similarity,
                        "text_preview": r.text[:120],
                    })

                best_sop_id = max(sop_scores, key=sop_scores.get)
                raw_similarity = sop_scores[best_sop_id]
                retrieved_chunks = [r.to_dict() for r in results]

                # Get full SOP doc for steps
                full_sop = qdrant.get_document(best_sop_id)
                selected = next(r for r in results if r.sop_id == best_sop_id)
                sop_title = selected.payload.get("title", "Unknown SOP")
                steps = full_sop.get("steps", []) if full_sop else []
                equipment_matched = selected.payload.get("equipment", "")

        except Exception as e:
            logger.warning(f"[SopRetriever] Qdrant search failed: {e}. Falling back to BM25.")
            retrieval_method = "bm25"
            # BM25 Fallback
            try:
                bm25, sops = get_bm25_fallback()
                tokens = re.findall(r"[A-Za-z0-9_\-]+", query_context.lower())
                raw_scores = bm25.get_scores(tokens)
                best_idx = max(range(len(raw_scores)), key=lambda idx: raw_scores[idx])
                max_s = float(max(raw_scores))
                raw_similarity = max_s
                best_sop = sops[best_idx]
                best_sop_id = best_sop.get("sop_id", "UNKNOWN")
                sop_title = best_sop.get("title", "Unknown SOP")
                steps = best_sop.get("steps", [])
                equipment_matched = best_sop.get("equipment_id", "")
                retrieved_chunks = [{"text": s, "section": "step", "sop_id": best_sop_id} for s in steps[:5]]
                candidates_log = [{"sop_id": sops[i].get("sop_id"), "keyword_score": float(raw_scores[i])}
                                   for i in range(len(sops))]
            except Exception as e2:
                logger.error(f"[SopRetriever] BM25 also failed: {e2}")
                best_sop_id, sop_title, steps, equipment_matched = "SOP-NONE", "No SOP Found", [], ""

        # Build why_retrieved
        symptoms = []
        if story and story.steps:
            symptoms = [s.description for s in story.steps[:4]]

        why_retrieved = {
            "incident": story.causal_label if story else "Unknown",
            "equipment": equipment_matched,
            "alarm": ((telemetry_snapshot or {}).get("alarm") or {}).get("alarm_id") or primary_tag or "N/A",
            "symptoms": symptoms,
            "likely_contributor": evidence.likely_contributor_tag if evidence else "N/A",
            "matching_section": retrieved_chunks[0].get("section", "") if retrieved_chunks else "",
            "semantic_similarity": raw_similarity if retrieval_method == "qdrant_vector_search" else None,
            "keyword_score": raw_similarity if retrieval_method == "bm25" else None,
            "retrieval_method": retrieval_method,
            "embedding_model": "all-MiniLM-L6-v2",
        }

        # Build rag_trace for debug endpoint
        rag_trace = {
            "event_id": event_id,
            "timestamp": timestamp,
            "query_context": query_context,
            "query_embedding_model": "all-MiniLM-L6-v2",
            "retrieval_method": retrieval_method,
            "top_k_requested": top_k,
            "candidates": candidates_log,
            "selected_sop_id": best_sop_id,
            "semantic_similarity": raw_similarity if retrieval_method == "qdrant_vector_search" else None,
            "keyword_score": raw_similarity if retrieval_method == "bm25" else None,
            "retrieved_chunks": retrieved_chunks,
            "process_context": telemetry_snapshot or {},
        }
        RAG_TRACE_STORE[event_id] = rag_trace

        sop_match = SopMatch(
            event_id=event_id,
            sop_id=best_sop_id,
            sop_title=sop_title,
            title=sop_title,
            revision=(retrieved_chunks[0].get("revision", "") if retrieved_chunks else ""),
            semantic_similarity=round(raw_similarity, 6) if retrieval_method == "qdrant_vector_search" else None,
            match_score=round(raw_similarity, 4) if retrieval_method == "qdrant_vector_search" else 0.0,
            retrieval_method=retrieval_method,
            embedding_model="all-MiniLM-L6-v2",
            query_context=query_context,
            steps=steps,
            source="embedding" if retrieval_method == "qdrant_vector_search" else "bm25",
            why_retrieved=why_retrieved,
            retrieved_chunks=retrieved_chunks,
            chunks=retrieved_chunks,
            rag_trace=rag_trace,
        )

        if persist and self.db:
            self.db.save_sop_match(sop_match)

        logger.info(
            f"[SopRetriever] event={event_id} -> SOP={best_sop_id} "
            f"semantic_similarity={raw_similarity:.4f} method={retrieval_method}"
        )
        return sop_match
