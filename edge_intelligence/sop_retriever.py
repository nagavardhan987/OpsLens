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
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from models import EventStory, Evidence, SopMatch
from database import Database
from embed_index import load_all_sops, SOP_DIR
from tag_registry import get_tag_entry

logger = logging.getLogger("opslens.sop_retriever")

_EMBED_MODEL = None
_QDRANT_STORE = None
_QDRANT_LAST_INIT_ATTEMPT = 0.0
_QDRANT_RETRY_INTERVAL_SECONDS = 5.0
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
    global _QDRANT_STORE, _QDRANT_LAST_INIT_ATTEMPT
    now = time.monotonic()
    needs_init = _QDRANT_STORE is None
    if not needs_init:
        try:
            offline = not _QDRANT_STORE.health().get("connected")
        except Exception:
            offline = True
        needs_init = offline and now - _QDRANT_LAST_INIT_ATTEMPT >= _QDRANT_RETRY_INTERVAL_SECONDS
    if needs_init:
        from vector_store.qdrant_store import QdrantVectorStore
        _QDRANT_LAST_INIT_ATTEMPT = now
        _QDRANT_STORE = QdrantVectorStore()
        # Auto-ingest bundled SOPs only after confirming the existing service
        # and collection are reachable. count()==0 also describes an offline
        # client, and attempting writes in that state obscured the real outage.
        health = _QDRANT_STORE.health()
        if health.get("connected") and _QDRANT_STORE.count() == 0:
            logger.info("[SopRetriever] Qdrant is empty. Auto-ingesting SOPs...")
            from ingest_sops import ingest
            ingest(vector_store=_QDRANT_STORE)
        elif not health.get("connected"):
            logger.warning("[SopRetriever] Qdrant unavailable; preserving service state and relying on the configured retrieval fallback.")
    return _QDRANT_STORE


def get_bm25_fallback():
    global _BM25_INDEX, _BM25_SOPS
    if _BM25_INDEX is None:
        from embed_index import format_sop_for_indexing
        from rank_bm25 import BM25Okapi
        _BM25_SOPS = []
        for sop in load_all_sops(SOP_DIR):
            pages = sop.get("content_pages") or []
            if pages:
                for page in pages:
                    page_text = str(page.get("text") or "").strip()
                    if not page_text:
                        continue
                    page_ids = re.findall(r"SOP-[A-Z]{3}-\d{3}", page_text)
                    _BM25_SOPS.append({
                        **sop,
                        "steps": [page_text],
                        "page": page.get("page"),
                        "section_title": page.get("section_title") or "Manual page",
                        "keywords": list(dict.fromkeys([*(sop.get("keywords") or []), *page_ids])),
                    })
            else:
                _BM25_SOPS.append(sop)

        # Uploaded PDFs are searchable while Qdrant is unavailable. Keep each
        # page as a separate passage so the citation retains its source page.
        try:
            from pdf_sop_ingestion import PDF_DIR, get_pdf_path, _chunk_page
            import fitz
            indexed_document_ids = {str(item.get("document_id") or "") for item in _BM25_SOPS}
            for metadata_path in PDF_DIR.glob("*.json") if PDF_DIR.exists() else []:
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    document_id = str(metadata.get("document_id") or "")
                    if document_id and document_id in indexed_document_ids:
                        continue
                    pdf_path = get_pdf_path(metadata["sop_id"], metadata.get("revision", ""), metadata.get("sha256", ""))
                    with fitz.open(pdf_path) as pdf:
                        for page_number, page in enumerate(pdf, start=1):
                            text = page.get_text("text").strip()
                            for chunk_index, chunk in enumerate(_chunk_page(text), start=1):
                                ids = re.findall(r"SOP-[A-Z]{3}-\d{3}", chunk)
                                heading = next((line.strip() for line in chunk.splitlines() if line.strip()), f"Page {page_number}")
                                _BM25_SOPS.append({
                                    **metadata,
                                    "sop_id": metadata["sop_id"],
                                    "document_id": document_id or metadata["sop_id"],
                                    "title": metadata.get("title") or metadata["sop_id"],
                                    "equipment_id": metadata.get("equipment") or "",
                                    "equipment_type": metadata.get("equipment_type") or "",
                                    "steps": [chunk],
                                    "page": page_number,
                                    "section_title": heading[:180],
                                    "keywords": list(dict.fromkeys([*(metadata.get("keywords") or []), *ids])),
                                })
                except Exception as exc:
                    logger.info("Local PDF page search unavailable for one document (%s)", type(exc).__name__)
        except Exception as exc:
            logger.info("Local PDF BM25 expansion unavailable (%s)", type(exc).__name__)
        corpus = [re.findall(r"[A-Za-z0-9_\-]+", format_sop_for_indexing(s).lower())
                  for s in _BM25_SOPS]
        _BM25_INDEX = BM25Okapi(corpus)
    return _BM25_INDEX, _BM25_SOPS


def _equipment_matches(document: Dict[str, Any], equipment: Optional[str]) -> bool:
    """Do not return a procedure authored for another equipment unit."""
    if not equipment:
        return True
    document_equipment = str(document.get("equipment") or document.get("equipment_id") or "").strip()
    if (str(document.get("equipment_type") or "").casefold() == "wastewater treatment"
            and equipment.strip().casefold().startswith(("liftstation-", "inletworks-", "aerationbasin-", "tertiarytreatment-"))):
        return True
    # Generic documents still need an explicit equipment match; otherwise a
    # semantically similar procedure can leak across unrelated assets.
    return document_equipment.casefold() == equipment.strip().casefold()


class SopRetriever:
    """
    SOP retrieval engine using Qdrant vector similarity search.
    Embedding model: all-MiniLM-L6-v2 (SentenceTransformer)
    Vector store: local Qdrant service (or persistent embedded Qdrant)
    """

    def __init__(self, db: Optional[Database] = None, force_source: Optional[str] = None):
        self.db = db
        if force_source not in (None, "qdrant_vector_search", "bm25"):
            raise ValueError("force_source must be qdrant_vector_search, bm25, or None")
        self.force_source = force_source

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
            try:
                equipment = get_tag_entry(evidence.likely_contributor_tag).equipment_id
            except KeyError:
                equipment = None
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

    def build_query(self, story=None, evidence=None, primary_tag=None, telemetry_snapshot=None):
        """Backward-compatible alias for callers using the pre-Qdrant API."""
        return self.build_contextual_query(
            story=story,
            evidence=evidence,
            primary_tag=primary_tag,
            telemetry_snapshot=telemetry_snapshot,
        )

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
        custom_query: Optional[str] = None,
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

        query_context = custom_query or self.build_contextual_query(story, evidence, primary_tag, telemetry_snapshot)
        timestamp = datetime.now(timezone.utc).isoformat()
        equipment_filter = (telemetry_snapshot or {}).get("equipment")
        if not equipment_filter and primary_tag:
            try:
                from tag_registry import get_tag_entry
                equipment_filter = get_tag_entry(primary_tag).equipment_id
            except (KeyError, AttributeError):
                equipment_filter = None

        # Attempt Qdrant semantic search
        match = None
        retrieval_method = "qdrant_vector_search"
        candidates_log = []
        raw_similarity = 0.0
        retrieved_chunks = []
        query_embedding = None
        retrieval_status = "no_match"
        retrieval_error = None

        try:
            if self.force_source == "bm25":
                raise RuntimeError("BM25 selected by caller")
            model = get_embed_model()
            query_embedding = model.encode([query_context], convert_to_numpy=True)[0]
            qdrant = get_qdrant_store()
            results = qdrant.search(query_vector=query_embedding.tolist(), top_k=top_k,
                                    equipment_filter=equipment_filter,
                                    plant_area_filter=telemetry_snapshot.get("plant_area") if telemetry_snapshot else None)
            if equipment_filter:
                results = [result for result in results
                           if _equipment_matches(result.payload, equipment_filter)]

            if not results:
                raise RuntimeError("Qdrant returned no SOP chunks")
            if results:
                # Group by SOP revision when available so a revision's chunks
                # and citation metadata are never mixed with another version.
                sop_scores: Dict[tuple[str, str], float] = {}
                for r in results:
                    sid = r.sop_id
                    doc_id = str(r.payload.get("document_id") or sid)
                    version_key = (sid, doc_id)
                    if version_key not in sop_scores or r.similarity > sop_scores[version_key]:
                        sop_scores[version_key] = r.similarity
                    candidates_log.append({
                        "sop_id": sid,
                        "chunk_id": r.chunk_id,
                        "section": r.payload.get("section", ""),
                        "similarity": r.similarity,
                        "text_preview": r.text[:120],
                    })

                best_sop_id, best_document_id = max(sop_scores, key=sop_scores.get)
                raw_similarity = sop_scores[(best_sop_id, best_document_id)]
                retrieved_chunks = [r.to_dict() for r in results
                                    if r.sop_id == best_sop_id
                                    and str(r.payload.get("document_id") or r.sop_id) == best_document_id]
                retrieval_status = "match_found" if retrieved_chunks else "no_match"

                # Get full SOP doc for steps
                try:
                    full_sop = qdrant.get_document(best_sop_id, document_id=best_document_id)
                except TypeError:
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
                eligible_indices = [i for i, sop in enumerate(sops)
                                    if _equipment_matches(sop, equipment_filter)]
                max_s = max((float(raw_scores[i]) for i in eligible_indices), default=0.0)
                raw_similarity = max_s
                candidates_log = [{"sop_id": sops[i].get("sop_id"), "keyword_score": float(raw_scores[i])}
                                   for i in eligible_indices]
                if max_s > 0:
                    if max_s <= 0:
                        best_sop_id, sop_title, steps, equipment_matched = "SOP-NONE", "No relevant SOP found", [], ""
                        retrieved_chunks = []
                    else:
                        best_idx = max(eligible_indices, key=lambda idx: float(raw_scores[idx]))
                        best_sop = sops[best_idx]
                        best_sop_id = best_sop.get("sop_id", "UNKNOWN")
                        sop_title = best_sop.get("title", "Unknown SOP")
                        steps = best_sop.get("steps", [])
                        equipment_matched = best_sop.get("equipment_id", "")
                        retrieved_chunks = [
                            {
                                "text": s,
                                "section": f"Step {idx}",
                                "sop_id": best_sop_id,
                                "document_id": best_sop.get("document_id") or best_sop_id,
                                "step_number": idx,
                                "step_title": best_sop.get("section_title") or f"Step {idx}",
                                "title": best_sop.get("title"),
                                "revision": best_sop.get("revision"),
                                "page": best_sop.get("page"),
                                "source_pdf": best_sop.get("source_pdf"),
                                "document_status": best_sop.get("document_status"),
                                "approval_status": best_sop.get("approval_status", "unverified"),
                                "approved": best_sop.get("approved") is True,
                            }
                            for idx, s in enumerate(steps[:1], start=1)
                        ]
                        retrieval_status = "match_found" if retrieved_chunks else "no_match"
                else:
                    best_sop_id, sop_title, steps, equipment_matched = "SOP-NONE", "No relevant SOP found", [], ""
                    retrieved_chunks = []
                    retrieval_status = "no_match"
            except Exception as e2:
                logger.error("[SopRetriever] BM25 retrieval unavailable (%s)", type(e2).__name__)
                best_sop_id, sop_title, steps, equipment_matched = "SOP-NONE", "No SOP Found", [], ""
                retrieval_status = "unavailable"
                retrieval_error = "retrieval_unavailable"

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
            "retrieval_status": retrieval_status,
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
            "retrieval_status": retrieval_status,
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
            source=("unavailable" if retrieval_status == "unavailable" else
                    "embedding" if retrieval_method == "qdrant_vector_search" else "bm25"),
            why_retrieved=why_retrieved,
            retrieved_chunks=retrieved_chunks,
            chunks=retrieved_chunks,
            rag_trace=rag_trace,
            retrieval_status=retrieval_status,
            retrieval_error=retrieval_error,
        )

        if persist and self.db:
            self.db.save_sop_match(sop_match)

        score_name = "semantic_similarity" if retrieval_method == "qdrant_vector_search" else "keyword_score"
        logger.info(
            f"[SopRetriever] event={event_id} -> SOP={best_sop_id} "
            f"{score_name}={raw_similarity:.4f} method={retrieval_method}"
        )
        return sop_match
