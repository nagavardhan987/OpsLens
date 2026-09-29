"""
OpsLens - SOP Ingestion Script

Loads all SOP JSON documents from sop_documents/,
chunks them into logical sections,
embeds each chunk using all-MiniLM-L6-v2,
and upserts into the Qdrant vector store.

Usage:
    python ingest_sops.py

The orchestrator calls this at startup to ensure Qdrant is populated.
"""
import sys
import json
import uuid
import logging
from pathlib import Path
from typing import List, Dict, Any

SOP_DIR = Path(__file__).resolve().parent / "sop_documents"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("opslens.ingest")


def chunk_sop(sop: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Split an SOP document into meaningful text chunks.
    Each chunk gets: sop_id, title, equipment, section, page, text.
    """
    sop_id = sop.get("sop_id", "UNKNOWN")
    title = sop.get("title", "")
    equipment = sop.get("equipment_id", "")
    keywords = sop.get("keywords", [])
    ref_limits = sop.get("reference_limits", {})
    steps = sop.get("steps", [])

    chunks = []
    base_payload = {
        "document_id": sop_id,
        "document_name": sop.get("document_name", title),
        "sop_id": sop_id,
        "title": title,
        "equipment": equipment,
        "equipment_type": sop.get("equipment_type", equipment),
        "plant_area": sop.get("plant_area", ""),
        "revision": sop.get("revision", "1.0"),
        "effective_date": sop.get("effective_date", ""),
        "source": "OpsLens SOP Knowledge Base",
        "keywords": keywords,
        "reference_limits": ref_limits,
        "tags": sop.get("tags", []),
    }

    # Chunk 1: Header / Overview
    header_text = (
        f"SOP: {title}\n"
        f"SOP ID: {sop_id}\n"
        f"Equipment: {equipment}\n"
        f"Keywords: {', '.join(keywords)}\n"
        f"Reference limits: {json.dumps(ref_limits)}"
    )
    chunks.append({
        **base_payload,
        "chunk_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{sop_id}::header")),
        "section": "header",
        "page": 1,
        "text": header_text,
    })

    # Chunk per step
    for idx, step in enumerate(steps, start=1):
        step_text = f"Step {idx}: {step}"
        chunks.append({
            **base_payload,
            "chunk_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{sop_id}::step::{idx}")),
            "section": "step",
            "page": idx,
            "text": step_text,
            "step_index": idx,
            "instruction": step,
        })

    # Chunk: All steps combined (for full-context matching)
    if steps:
        all_steps_text = f"Procedure for {title}:\n" + "\n".join(
            [f"{i}. {s}" for i, s in enumerate(steps, 1)]
        )
        chunks.append({
            **base_payload,
            "chunk_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{sop_id}::all_steps")),
            "section": "procedure",
            "page": 0,
            "text": all_steps_text,
        })

    return chunks


def ingest(vector_store=None):
    """
    Main ingestion function.
    Loads SOPs, chunks them, embeds with SentenceTransformer, upserts into Qdrant.
    """
    if vector_store is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from vector_store.qdrant_store import QdrantVectorStore
        vector_store = QdrantVectorStore()

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)

    sop_files = sorted(SOP_DIR.glob("*.json"))
    if not sop_files:
        logger.warning(f"[Ingest] No SOP files found in {SOP_DIR}")
        return 0

    logger.info(f"[Ingest] Found {len(sop_files)} SOP documents")

    from vector_store.base import VectorStoreDocument
    all_docs = []

    for path in sop_files:
        with open(path, encoding="utf-8") as f:
            sop = json.load(f)
        chunks = chunk_sop(sop)
        texts = [c["text"] for c in chunks]
        embeddings = model.encode(texts, convert_to_numpy=True)
        logger.info(f"[Ingest] {sop.get('sop_id')} -> {len(chunks)} chunks embedded")

        for chunk, emb in zip(chunks, embeddings):
            all_docs.append(VectorStoreDocument(
                chunk_id=chunk["chunk_id"],
                document_id=chunk["sop_id"],
                sop_id=chunk["sop_id"],
                text=chunk["text"],
                embedding=emb.tolist(),
                payload=chunk,
            ))

    count = vector_store.upsert(all_docs)
    logger.info(f"[Ingest] Done. {count} total chunks upserted into Qdrant.")
    return count


if __name__ == "__main__":
    total = ingest()
    print(f"Ingested {total} chunks into Qdrant.")
