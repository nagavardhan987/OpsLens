"""Local PDF SOP storage and page-aware Qdrant ingestion helpers."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from embed_index import SOP_DIR

PDF_DIR = SOP_DIR / "ingested_pdfs"
MAX_PDF_BYTES = 25 * 1024 * 1024
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 160


def safe_sop_key(sop_id: str) -> str:
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", sop_id).strip("._-")
    if not key:
        raise ValueError("SOP ID must contain letters or numbers.")
    return key[:100]


def _extract_pages(pdf_bytes: bytes) -> List[str]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF support is not installed. Install dependencies from edge_intelligence/requirements.txt.") from exc

    pages = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            if pdf.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported. Upload an unlocked PDF.")
            for page in pdf:
                pages.append(page.get_text("text").strip())
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not read this PDF: {exc}") from exc

    if not any(pages):
        raise ValueError("No selectable text was found in this PDF. Scanned PDFs need OCR before ingestion.")
    return pages


def _chunk_page(text: str) -> List[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + CHUNK_SIZE, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start + CHUNK_SIZE // 2, end)
            if boundary > start:
                end = boundary
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def list_sop_library() -> List[Dict[str, Any]]:
    """List bundled JSON procedures and locally ingested PDFs for the UI."""
    docs: Dict[str, Dict[str, Any]] = {}
    for path in sorted(SOP_DIR.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                item = json.load(f)
            sop_id = item.get("sop_id")
            if sop_id:
                docs[sop_id] = {
                    "sop_id": sop_id,
                    "title": item.get("title", path.stem),
                    "equipment": item.get("equipment_id", item.get("equipment", "")),
                    "revision": item.get("revision", "1.0"),
                    "source_pdf": None,
                    "storage_type": "bundled_json",
                }
        except (OSError, json.JSONDecodeError):
            continue

    if PDF_DIR.exists():
        for metadata_path in PDF_DIR.glob("*.json"):
            try:
                with metadata_path.open(encoding="utf-8") as f:
                    item = json.load(f)
                docs[item["sop_id"]] = {**item, "storage_type": "local_pdf"}
            except (OSError, json.JSONDecodeError, KeyError):
                continue
    return sorted(docs.values(), key=lambda item: item.get("title", "").lower())


def get_pdf_path(sop_id: str) -> Path:
    return PDF_DIR / f"{safe_sop_key(sop_id)}.pdf"


def ingest_pdf(pdf_bytes: bytes, filename: str, metadata: Dict[str, str], store) -> Dict[str, Any]:
    """Extract, chunk, embed, save source locally, and index PDF SOP in Qdrant."""
    if not pdf_bytes or len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError("PDF must be between 1 byte and 25 MB.")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF.")

    sop_id = metadata["sop_id"].strip()
    title = metadata["title"].strip()
    if not sop_id or not title:
        raise ValueError("SOP ID and title are required.")
    key = safe_sop_key(sop_id)
    pages = _extract_pages(pdf_bytes)
    source_name = Path(filename).name[:180] or f"{key}.pdf"
    revision = (metadata.get("revision") or "1.0").strip()
    equipment = (metadata.get("equipment") or "").strip()
    equipment_type = (metadata.get("equipment_type") or equipment).strip()
    plant_area = (metadata.get("plant_area") or "").strip()
    effective_date = (metadata.get("effective_date") or "").strip()
    document_id = sop_id
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()

    chunk_rows = []
    for page_number, page_text in enumerate(pages, start=1):
        for chunk_number, text in enumerate(_chunk_page(page_text), start=1):
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                      f"opslens-pdf:{sop_id}:{revision}:{pdf_hash}:{page_number}:{chunk_number}"))
            chunk_rows.append({
                "document_id": document_id,
                "document_name": source_name,
                "sop_id": sop_id,
                "title": title,
                "revision": revision,
                "equipment": equipment,
                "equipment_type": equipment_type,
                "plant_area": plant_area,
                "section": "content",
                "page": page_number,
                "source": source_name,
                "source_pdf": source_name,
                "effective_date": effective_date,
                "chunk_id": chunk_id,
                "text": text,
                "instruction": text,
                "chunk_number": chunk_number,
                "page_count": len(pages),
            })

    if not chunk_rows:
        raise ValueError("The PDF did not contain text that could be indexed.")

    # Load the same on-device model used by incident retrieval.
    from sop_retriever import get_embed_model
    from vector_store.base import VectorStoreDocument
    model = get_embed_model()
    embedding_texts = [
        f"SOP: {title}\nEquipment: {equipment} ({equipment_type})\nPlant area: {plant_area}\n"
        f"Revision: {revision}\nPage {row['page']} content: {row['text']}"
        for row in chunk_rows
    ]
    embeddings = model.encode(embedding_texts, convert_to_numpy=True)
    vector_docs = [VectorStoreDocument(
        chunk_id=row["chunk_id"], document_id=row["document_id"], sop_id=sop_id,
        text=row["text"], embedding=embedding.tolist(), payload=row,
    ) for row, embedding in zip(chunk_rows, embeddings)]

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = get_pdf_path(sop_id)
    metadata_path = PDF_DIR / f"{key}.json"
    temp_pdf = pdf_path.with_suffix(".pdf.tmp")
    temp_pdf.write_bytes(pdf_bytes)

    # Remove the older indexed revision only after extraction and embedding
    # have succeeded, then atomically replace its local source file.
    if not store.delete_by_document_id(document_id):
        temp_pdf.unlink(missing_ok=True)
        raise RuntimeError("Could not replace the existing SOP chunks in Qdrant.")
    temp_pdf.replace(pdf_path)
    try:
        indexed_chunks = store.upsert(vector_docs)
    except Exception:
        pdf_path.unlink(missing_ok=True)
        raise

    record = {
        "sop_id": sop_id,
        "title": title,
        "equipment": equipment,
        "equipment_type": equipment_type,
        "plant_area": plant_area,
        "revision": revision,
        "effective_date": effective_date,
        "source_pdf": source_name,
        "source": "local_pdf",
        "page_count": len(pages),
        "chunk_count": indexed_chunks,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "sha256": pdf_hash,
    }
    metadata_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {**record, "stages": [
        {"name": "PDF uploaded", "complete": True},
        {"name": "Text extracted", "complete": True, "detail": f"{len(pages)} pages"},
        {"name": "Chunks prepared", "complete": True, "detail": f"{len(chunk_rows)} chunks"},
        {"name": "SentenceTransformer embedded", "complete": True, "detail": "all-MiniLM-L6-v2"},
        {"name": "Indexed in Qdrant", "complete": True, "detail": f"{indexed_chunks} chunks"},
    ]}
