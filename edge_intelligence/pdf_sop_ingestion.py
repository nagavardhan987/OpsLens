"""Local PDF SOP storage and page-aware Qdrant ingestion helpers."""
import hashlib
import json
import os
import logging
import math
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
logger = logging.getLogger("opslens.pdf_ingestion")


class PdfExtractionError(ValueError):
    """PDF was accepted as a file, but its text could not be extracted safely."""


class PdfIndexingError(RuntimeError):
    """Extracted PDF content could not be embedded or indexed."""

    def __init__(self, message: str, code: str = "vector_indexing_failed"):
        super().__init__(message)
        self.code = code


def safe_sop_key(sop_id: str) -> str:
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", sop_id).strip("._-")
    if not key:
        raise ValueError("SOP ID must contain letters or numbers.")
    return key[:100]


def _extract_pages(pdf_bytes: bytes) -> List[str]:
    try:
        import fitz
    except ImportError as exc:
        raise PdfExtractionError("PDF text extraction is unavailable because the PDF support dependency is missing.") from exc

    pages = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            if pdf.is_encrypted:
                raise PdfExtractionError("Encrypted PDFs cannot be extracted. Upload an unlocked PDF.")
            for page in pdf:
                pages.append(page.get_text("text").strip())
    except PdfExtractionError:
        raise
    except Exception as exc:
        raise PdfExtractionError("The PDF could not be read for text extraction.") from exc

    if not any(pages):
        raise PdfExtractionError("No selectable text was found. This may be a scanned PDF; OCR or manual review is required before ingestion.")
    return pages


def _chunk_page(text: str) -> List[str]:
    # Keep headings, numbered instructions, warnings and paragraph boundaries
    # together where practical instead of flattening the page before chunking.
    paragraphs = [re.sub(r"[ \t]+", " ", block).strip()
                  for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not paragraphs:
        paragraphs = [re.sub(r"\s+", " ", text).strip()] if text.strip() else []
    chunks: List[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > CHUNK_SIZE:
            if current:
                chunks.append(current)
                current = ""
            normalized = re.sub(r"\s+", " ", paragraph)
            start = 0
            while start < len(normalized):
                end = min(start + CHUNK_SIZE, len(normalized))
                if end < len(normalized):
                    boundary = normalized.rfind(" ", start + CHUNK_SIZE // 2, end)
                    if boundary > start:
                        end = boundary
                chunks.append(normalized[start:end].strip())
                if end >= len(normalized):
                    break
                start = max(end - CHUNK_OVERLAP, start + 1)
            continue
        if current and len(current) + len(paragraph) + 2 > CHUNK_SIZE:
            chunks.append(current)
            # Keep a short tail from the prior chunk so a warning and its
            # neighboring instruction are less likely to become detached.
            current = current[-CHUNK_OVERLAP:] + "\n" + paragraph
        else:
            current = f"{current}\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def _extraction_warnings(pdf_bytes: bytes) -> List[str]:
    """Flag embedded visual content that selectable-text extraction cannot interpret."""
    try:
        import fitz
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            image_pages = [str(index) for index, page in enumerate(pdf, start=1)
                           if page.get_images(full=True)]
            table_like_pages = []
            for index, page in enumerate(pdf, start=1):
                page_text = page.get_text("text")
                aligned_rows = sum(bool(re.search(r"\S\s{3,}\S", line)) for line in page_text.splitlines())
                if aligned_rows >= 3:
                    table_like_pages.append(str(index))
        warnings = []
        if image_pages:
            warnings.append(f"Pages {', '.join(image_pages)} contain embedded images; image content was not OCR-interpreted and requires manual review.")
        if table_like_pages:
            warnings.append(f"Pages {', '.join(table_like_pages)} may contain tables; extracted column relationships require manual review.")
        return warnings
    except Exception:
        return ["Visual-content review could not be completed; verify diagrams and tables manually."]


def list_sop_library() -> List[Dict[str, Any]]:
    """List locally ingested PDFs and each procedure registered in bundled manuals."""
    docs: Dict[str, Dict[str, Any]] = {}
    for path in sorted(SOP_DIR.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                item = json.load(f)
            sop_id = item.get("sop_id")
            if sop_id:
                docs[f"{sop_id}:bundled"] = {
                    "sop_id": sop_id,
                    "title": item.get("title", path.stem),
                    "equipment": item.get("equipment_id", item.get("equipment", "")),
                    "revision": item.get("revision", "1.0"),
                    "approved": item.get("approved") is True,
                    "approval_status": item.get("approval_status", "unverified"),
                    "approval_reference": item.get("approval_reference"),
                    "document_status": item.get("document_status", "Approval status not verified"),
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
                docs[f"{item['sop_id']}:{item.get('revision', 'unknown')}:{item.get('sha256', '')}"] = {**item, "storage_type": "local_pdf"}
            except (OSError, json.JSONDecodeError, KeyError):
                continue
    # A bundled manual is one source file containing distinct, page-addressable
    # procedures. Expose each registered procedure as a searchable library item
    # without duplicating or re-ingesting the PDF.
    try:
        from demo_sop_sections import DEMO_SOP_SECTIONS, load_demo_sop_document
        manuals = [json.loads(path.read_text(encoding="utf-8")) for path in PDF_DIR.glob("*.json")
                   if json.loads(path.read_text(encoding="utf-8")).get("sop_id") == "SOP-MAN-000"]
        if manuals:
            manual = max(manuals, key=lambda item: item.get("indexed_at", ""))
            for entry in manual.get("sop_register", []):
                sop_id = entry.get("sop_id")
                if sop_id not in DEMO_SOP_SECTIONS:
                    continue
                section_document = load_demo_sop_document(sop_id)
                docs[f"{sop_id}:manual:{manual.get('sha256', '')}"] = {
                    **entry,
                    "sop_id": sop_id,
                    "title": entry.get("title", sop_id),
                    "equipment": entry.get("process_area", ""),
                    "revision": manual.get("revision", "0"),
                    "revision_label": manual.get("revision_label", "0 (Draft for review)"),
                    "approved": False,
                    "approval_status": "draft",
                    "approval_reference": None,
                    "document_status": manual.get("document_status", "Reference only — not approved."),
                    "source_pdf": manual.get("source_pdf"),
                    "sha256": manual.get("sha256"),
                    "source_pages": (section_document or {}).get("source_pages", list(DEMO_SOP_SECTIONS[sop_id]["pages"])),
                    "content_available": bool(section_document and section_document.get("content_pages")),
                    "storage_type": "local_pdf_section",
                    "extraction_status": manual.get("extraction_status", "unknown"),
                }
    except (OSError, ValueError, ImportError):
        logger.exception("Unable to expand bundled SOP register into library records")
    return sorted(docs.values(), key=lambda item: item.get("title", "").lower())


def get_pdf_path(sop_id: str, revision: str = "", sha256: str = "") -> Path:
    """Resolve a stored PDF version; without version metadata return the latest indexed revision."""
    key = safe_sop_key(sop_id)
    if revision and sha256:
        rev_key = safe_sop_key(revision)
        return PDF_DIR / f"{key}.{rev_key}.{sha256[:12]}.pdf"
    records = []
    if PDF_DIR.exists():
        for metadata_path in PDF_DIR.glob(f"{key}.*.json"):
            try:
                record = json.loads(metadata_path.read_text(encoding="utf-8"))
                if record.get("sop_id") == sop_id:
                    records.append((record.get("indexed_at", ""), record))
            except (OSError, json.JSONDecodeError):
                continue
    if not records:
        return PDF_DIR / f"{key}.pdf"
    latest = max(records, key=lambda item: item[0])[1]
    return get_pdf_path(sop_id, latest.get("revision", "unknown"), latest.get("sha256", ""))


def ingest_pdf(pdf_bytes: bytes, filename: str, metadata: Dict[str, str], store, progress_callback=None) -> Dict[str, Any]:
    """Extract, chunk, embed, save source locally, and index PDF SOP in Qdrant."""
    def report_stage(name: str, status: str, detail: str = "") -> None:
        if callable(progress_callback):
            try:
                progress_callback({"name": name, "status": status, "complete": status == "complete", "detail": detail})
            except Exception:
                pass

    if not pdf_bytes or len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError("PDF must be between 1 byte and 25 MB.")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF.")
    report_stage("PDF uploaded", "complete")

    sop_id = metadata["sop_id"].strip()
    title = metadata["title"].strip()
    if not sop_id or not title:
        raise ValueError("SOP ID and title are required.")
    key = safe_sop_key(sop_id)
    source_name = Path(filename).name[:180] or f"{key}.pdf"
    revision = (metadata.get("revision") or "unknown").strip()
    equipment = (metadata.get("equipment") or "").strip()
    equipment_type = (metadata.get("equipment_type") or equipment).strip()
    plant_area = (metadata.get("plant_area") or "").strip()
    effective_date = (metadata.get("effective_date") or "").strip()
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    # A versioned identity keeps previous revisions intact. Stable chunk IDs
    # make repeat ingestion of the same bytes and revision idempotent.
    document_id = f"{sop_id}::{revision}::{pdf_hash}"
    approval_status = "unverified"
    document_status = "Approval status not verified — uploaded PDF requires document-control review."

    # Report an actual duplicate only when both local source metadata and the
    # exact document revision are still present in the vector index.
    rev_key = safe_sop_key(revision)
    metadata_path = PDF_DIR / f"{key}.{rev_key}.{pdf_hash[:12]}.json"
    existing_pdf = get_pdf_path(sop_id, revision, pdf_hash)
    if metadata_path.is_file() and existing_pdf.is_file():
        try:
            existing_record = json.loads(metadata_path.read_text(encoding="utf-8"))
            document_lookup = getattr(store, "get_document", None)
            indexed = document_lookup(sop_id, document_id=document_id) if callable(document_lookup) else None
            if existing_record.get("document_id") == document_id and indexed:
                report_stage("Duplicate detected", "complete", "This source revision is already stored and indexed.")
                return {
                    **existing_record,
                    "duplicate": True,
                    "status": "duplicate",
                    "stages": [
                        {"name": "PDF received", "status": "complete", "complete": True},
                        {"name": "Duplicate detected", "status": "complete", "complete": True,
                         "detail": "The same source, SOP ID, and revision are already stored and indexed."},
                        {"name": "Approval check", "status": "unverified", "complete": False,
                         "detail": "Approval remains unverified; ingestion does not approve documents."},
                    ],
                }
        except Exception:
            # A failed duplicate check must not suppress a valid re-ingestion.
            pass

    report_stage("Text extraction", "running", "Reading selectable text and page boundaries.")
    pages = _extract_pages(pdf_bytes)
    cover_text = "\n".join(pages[:3]).casefold()
    if re.search(r"\b(?:draft for review|draft for approval|draft only)\b", cover_text):
        approval_status = "draft"
        document_status = (
            "Revision is marked Draft for review; the approval table is incomplete. "
            "Reference only — not an approved plant SOP. Numerical values are typical examples "
            "and require verification against plant design, equipment data, permits, and regulations."
        )
    extraction_warnings = _extraction_warnings(pdf_bytes)
    blank_pages = [str(number) for number, page in enumerate(pages, start=1) if not page.strip()]
    if blank_pages:
        extraction_warnings.append(
            f"Pages {', '.join(blank_pages)} produced no selectable text; verify whether OCR or manual review is needed."
        )
    extraction_status = "partial" if extraction_warnings else "complete"
    report_stage("Text extraction", extraction_status,
                 f"{len(pages)} pages; review extraction warnings." if extraction_warnings else f"{len(pages)} pages")
    if extraction_status == "partial":
        report_stage("OCR or manual review", "partial", "Some page content may not be represented in extracted text.")

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
                "sha256": pdf_hash,
                "approval_status": approval_status,
                "approved": False,
                "approval_reference": None,
                "document_status": document_status,
                "chunk_id": chunk_id,
                "text": text,
                "instruction": text,
                "chunk_number": chunk_number,
                "page_count": len(pages),
            })

    if not chunk_rows:
        raise ValueError("The PDF did not contain text that could be indexed.")
    report_stage("Sections prepared", "complete", f"{len(chunk_rows)} page-aware chunks")

    # Load the same on-device model used by incident retrieval.
    from sop_retriever import get_embed_model
    from vector_store.base import VectorStoreDocument
    from vector_store.qdrant_store import VECTOR_SIZE
    def store_keyword_only(reason_code: str, reason: str) -> Dict[str, Any]:
        """Qdrant/embeddings are optional: keep the source PDF and metadata so
        BM25 keyword retrieval can cite it, and say clearly that no vector
        index was written."""
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path = get_pdf_path(sop_id, revision, pdf_hash)
        pdf_path.write_bytes(pdf_bytes)
        record = {
            "sop_id": sop_id, "title": title, "equipment": equipment, "equipment_type": equipment_type,
            "plant_area": plant_area, "revision": revision, "effective_date": effective_date,
            "approval_status": approval_status, "approved": False, "approval_reference": None,
            "document_status": document_status, "source_pdf": source_name, "document_id": document_id,
            "manual_review_required": True, "extraction_warnings": extraction_warnings,
            "extraction_status": extraction_status, "source": "local_pdf", "page_count": len(pages),
            "chunk_count": len(chunk_rows), "indexed_at": datetime.now(timezone.utc).isoformat(),
            "sha256": pdf_hash, "index_method": "bm25_keyword_only", "vector_indexed": False,
            "vector_index_unavailable_reason": reason_code,
        }
        metadata_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        try:
            import sop_retriever
            sop_retriever._BM25_INDEX = None  # rebuild so the new document is searchable
            sop_retriever._BM25_SOPS = None
        except Exception:
            pass
        report_stage("Keyword index", "complete", "Stored for BM25 keyword retrieval (no vector index).")
        return {**record, "duplicate": False, "status": "stored_keyword_only", "stages": [
            {"name": "PDF uploaded", "status": "complete", "complete": True},
            {"name": "Text extraction", "status": extraction_status, "complete": True, "detail": f"{len(pages)} pages"},
            {"name": "Chunks prepared", "status": "complete", "complete": True, "detail": f"{len(chunk_rows)} chunks"},
            {"name": "Vector index", "status": "skipped", "complete": False, "detail": reason},
            {"name": "Keyword (BM25) retrieval", "status": "complete", "complete": True,
             "detail": "Searchable with BM25. Start Qdrant and install sentence-transformers, then re-ingest for vector search."},
            {"name": "Approval check", "status": "unverified", "complete": False,
             "detail": "DRAFT / REFERENCE ONLY — NOT APPROVED. Document-control review is required."},
        ]}

    keyword_fallback = os.environ.get("OPSLENS_PDF_BM25_FALLBACK", "true").strip().lower() in ("1", "true", "yes")
    try:
        report_stage("Embedding", "running", "Generating local sentence embeddings.")
        model = get_embed_model()
    except Exception as exc:
        if keyword_fallback:
            logger.warning("Embedding model unavailable (%s); storing %s for BM25 keyword retrieval only.", type(exc).__name__, sop_id)
            return store_keyword_only("embedding_model_unavailable",
                                      "Embedding model (sentence-transformers all-MiniLM-L6-v2) is not available on this PC.")
        logger.exception("PDF SOP embedding model initialization failed; sop_id=%s", sop_id)
        raise PdfIndexingError("The configured local embedding model is unavailable; the SOP was not indexed.", "embedding_model_unavailable") from exc
    embedding_texts = [
        f"SOP: {title}\nEquipment: {equipment} ({equipment_type})\nPlant area: {plant_area}\n"
        f"Revision: {revision}\nPage {row['page']} content: {row['text']}"
        for row in chunk_rows
    ]
    try:
        embeddings = model.encode(embedding_texts, convert_to_numpy=True)
    except Exception as exc:
        logger.exception("PDF SOP embedding generation failed; sop_id=%s chunks=%s", sop_id, len(chunk_rows))
        raise PdfIndexingError("Text was extracted, but the configured embedding model failed to generate vectors.", "embedding_generation_failed") from exc
    try:
        shape = tuple(embeddings.shape)
        if len(shape) != 2 or shape[0] != len(chunk_rows) or shape[1] != VECTOR_SIZE:
            raise ValueError(f"Embedding matrix shape {shape} does not match ({len(chunk_rows)}, {VECTOR_SIZE}).")
        if not all(math.isfinite(float(value)) for row in embeddings for value in row):
            raise ValueError("Embedding matrix contains non-finite values.")
    except Exception as exc:
        logger.exception("PDF SOP embedding output validation failed; sop_id=%s chunks=%s", sop_id, len(chunk_rows))
        raise PdfIndexingError(
            f"Embedding output is invalid for the configured Qdrant collection ({type(exc).__name__}); expected {len(chunk_rows)} finite vectors of size {VECTOR_SIZE}.",
            "embedding_output_invalid",
        ) from exc
    report_stage("Embedding", "complete", "all-MiniLM-L6-v2")
    vector_docs = [VectorStoreDocument(
        chunk_id=row["chunk_id"], document_id=row["document_id"], sop_id=sop_id,
        text=row["text"], embedding=embedding.tolist(), payload=row,
    ) for row, embedding in zip(chunk_rows, embeddings)]

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = get_pdf_path(sop_id, revision, pdf_hash)
    temp_pdf = pdf_path.with_suffix(".pdf.tmp")
    temp_pdf.write_bytes(pdf_bytes)
    try:
        report_stage("Qdrant indexing", "running", f"Writing {len(vector_docs)} extracted chunks.")
        indexed_chunks = store.upsert(vector_docs)
        if indexed_chunks != len(vector_docs):
            raise RuntimeError("The vector store confirmed fewer chunks than submitted.")
    except Exception as exc:
        temp_pdf.unlink(missing_ok=True)
        logger.exception(
            "PDF SOP vector upsert failed; sop_id=%s document_id=%s chunks=%s store_type=%s",
            sop_id, document_id, len(vector_docs), type(store).__name__,
        )
        if getattr(store, "_client", object()) is None and keyword_fallback:
            logger.warning("Qdrant unavailable; storing %s for BM25 keyword retrieval only.", sop_id)
            return store_keyword_only("qdrant_unavailable", "Qdrant is not reachable; no vector index was written.")
        if getattr(store, "_client", object()) is None:
            detail = getattr(store, "initialization_error", None)
            if detail and "10061" in detail:
                message = "Qdrant at the configured endpoint refused the connection. Start the existing Qdrant service and retry; the PDF was extracted but not indexed."
                code = "qdrant_connection_refused"
            elif detail:
                message = "Qdrant could not initialize the configured endpoint or the existing collection does not match the OpsLens vector schema. See backend logs for diagnostics; existing data was preserved."
                code = "qdrant_unavailable_or_incompatible"
            else:
                message = "Qdrant is unavailable. Check the configured service and collection; existing SOP revisions were preserved."
                code = "qdrant_unavailable"
        else:
            message = f"Qdrant rejected the extracted vectors or payload ({type(exc).__name__}). Existing SOP revisions were preserved. See backend logs for the full exception."
            code = "qdrant_upsert_rejected"
        raise PdfIndexingError(message, code) from exc
    temp_pdf.replace(pdf_path)
    report_stage("Qdrant indexing", "complete", f"{indexed_chunks} chunks")

    record = {
        "sop_id": sop_id,
        "title": title,
        "equipment": equipment,
        "equipment_type": equipment_type,
        "plant_area": plant_area,
        "revision": revision,
        "effective_date": effective_date,
        "approval_status": approval_status,
        "approved": False,
        "approval_reference": None,
        "document_status": document_status,
        "source_pdf": source_name,
        "document_id": document_id,
        "manual_review_required": True,
        "extraction_warnings": extraction_warnings,
        "extraction_status": extraction_status,
        "source": "local_pdf",
        "page_count": len(pages),
        "chunk_count": indexed_chunks,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "sha256": pdf_hash,
    }
    metadata_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {**record, "duplicate": False, "status": "partial_extraction" if extraction_warnings else "indexed", "stages": [
        {"name": "PDF uploaded", "status": "complete", "complete": True},
        {"name": "Text extraction", "status": extraction_status, "complete": True,
         "detail": f"{len(pages)} pages"},
        {"name": "Chunks prepared", "status": "complete", "complete": True, "detail": f"{len(chunk_rows)} chunks"},
        {"name": "Embedding generated", "status": "complete", "complete": True, "detail": "all-MiniLM-L6-v2"},
        {"name": "Indexed in Qdrant", "status": "complete", "complete": True, "detail": f"{indexed_chunks} chunks"},
        {"name": "Approval check", "status": "unverified", "complete": False,
         "detail": "DRAFT / REFERENCE ONLY — NOT APPROVED. Document-control review is required."},
    ]}
