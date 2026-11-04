import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pdf_sop_ingestion as ingestion


class FakeStore:
    def __init__(self, fail=False):
        self.docs = {}
        self.fail = fail
        self.delete_calls = []

    def upsert(self, documents):
        if self.fail:
            raise RuntimeError("index unavailable")
        for doc in documents:
            self.docs[doc.chunk_id] = doc
        return len(documents)

    def delete_by_document_id(self, document_id):
        self.delete_calls.append(document_id)
        return True

    def get_document(self, sop_id, document_id=None):
        matches = [doc for doc in self.docs.values()
                   if doc.sop_id == sop_id and (document_id is None or doc.document_id == document_id)]
        return {"sop_id": sop_id, "document_id": document_id} if matches else None


class UnavailableQdrantStore:
    _client = None
    initialization_error = "ConnectError: [WinError 10061] connection refused"

    def upsert(self, documents):
        raise RuntimeError(f"Qdrant client not available: {self.initialization_error}")


class FakeEmbedding:
    def encode(self, texts, convert_to_numpy=True):
        return np.array([[0.1] * 384 for _ in texts], dtype=np.float32)


class InvalidDimensionEmbedding:
    def encode(self, texts, convert_to_numpy=True):
        return np.array([[0.1, 0.2] for _ in texts], dtype=np.float32)


class TestPdfIngestionSafety(unittest.TestCase):
    def setUp(self):
        # Keep test writes inside the writable repository; Windows sandbox temp
        # directories can be unreadable to the Python process running tests.
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.store = FakeStore()
        self.metadata = {"sop_id": "SOP-TEST-01", "title": "Test procedure"}
        self.patches = [
            patch.object(ingestion, "PDF_DIR", Path(self.temp.name)),
            patch.object(ingestion, "_extract_pages", return_value=["Step 1. Inspect the source readings and record the observed state."]),
            patch("sop_retriever.get_embed_model", return_value=FakeEmbedding()),
            patch.object(ingestion, "_extraction_warnings", return_value=[]),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def ingest(self, data=b"%PDF-test", metadata=None):
        return ingestion.ingest_pdf(data, "procedure.pdf", metadata or self.metadata, self.store)

    def test_new_pdf_defaults_to_unverified_and_records_unknown_revision(self):
        result = self.ingest()
        self.assertEqual(result["revision"], "unknown")
        self.assertEqual(result["effective_date"], "")
        self.assertEqual(result["approval_status"], "unverified")
        self.assertFalse(result["approved"])
        self.assertIsNone(result["approval_reference"])
        self.assertEqual(result["status"], "indexed")
        self.assertTrue(result["manual_review_required"])
        self.assertEqual(self.store.delete_calls, [])

    def test_progress_callback_reports_extraction_embedding_and_indexing_stages(self):
        progress = []
        ingestion.ingest_pdf(
            b"%PDF-progress", "procedure.pdf", self.metadata, self.store,
            progress_callback=progress.append,
        )
        states = [(item["name"], item["status"]) for item in progress]
        self.assertIn(("Text extraction", "running"), states)
        self.assertIn(("Text extraction", "complete"), states)
        self.assertIn(("Embedding", "running"), states)
        self.assertIn(("Embedding", "complete"), states)
        self.assertIn(("Qdrant indexing", "running"), states)
        self.assertIn(("Qdrant indexing", "complete"), states)

    def test_partial_extraction_progress_calls_for_manual_review(self):
        self.patches[-1].stop()
        self.patches[-1] = patch.object(ingestion, "_extraction_warnings", return_value=["Page 2 contains an image."])
        self.patches[-1].start()
        progress = []
        ingestion.ingest_pdf(
            b"%PDF-partial-progress", "procedure.pdf", self.metadata, self.store,
            progress_callback=progress.append,
        )
        self.assertIn(("Text extraction", "partial"), [(item["name"], item["status"]) for item in progress])
        self.assertIn(("OCR or manual review", "partial"), [(item["name"], item["status"]) for item in progress])

    def test_same_pdf_and_revision_is_idempotent_without_deleting_other_records(self):
        first = self.ingest(metadata={**self.metadata, "revision": "A"})
        second = self.ingest(metadata={**self.metadata, "revision": "A"})
        self.assertEqual(first["document_id"], second["document_id"])
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(second["status"], "duplicate")
        self.assertTrue(second["duplicate"])
        self.assertTrue(any(stage["name"] == "Duplicate detected" for stage in second["stages"]))
        self.assertEqual(len(self.store.docs), 1)
        self.assertEqual(self.store.delete_calls, [])

    def test_extraction_warning_reports_partial_extraction_and_manual_review(self):
        self.patches[-1].stop()
        self.patches[-1] = patch.object(ingestion, "_extraction_warnings", return_value=["Page 2 contains an image; OCR/manual review required."])
        self.patches[-1].start()
        result = self.ingest()
        self.assertEqual(result["status"], "partial_extraction")
        self.assertEqual(result["extraction_status"], "partial")
        self.assertIn("OCR/manual review", result["extraction_warnings"][0])
        self.assertFalse(result["approved"])

    def test_scanned_or_unreadable_pdf_is_classified_as_extraction_failure(self):
        self.patches[1].stop()
        self.patches[1] = patch.object(ingestion, "_extract_pages", side_effect=ingestion.PdfExtractionError(
            "No selectable text was found. This may be a scanned PDF; OCR or manual review is required before ingestion."
        ))
        self.patches[1].start()
        with self.assertRaises(ingestion.PdfExtractionError):
            self.ingest()
        self.assertEqual(self.store.docs, {})

    def test_index_failure_is_classified_and_does_not_replace_existing_revision(self):
        self.store.fail = True
        with self.assertRaises(ingestion.PdfIndexingError):
            self.ingest()
        self.assertEqual(self.store.docs, {})
        self.assertFalse(any(Path(self.temp.name).glob("*.pdf")))

    def test_embedding_dimension_mismatch_is_reported_before_vector_store_write(self):
        self.patches[2].stop()
        self.patches[2] = patch("sop_retriever.get_embed_model", return_value=InvalidDimensionEmbedding())
        self.patches[2].start()
        with self.assertRaises(ingestion.PdfIndexingError) as caught:
            self.ingest()
        self.assertEqual(caught.exception.code, "embedding_output_invalid")
        self.assertIn("expected 1 finite vectors of size 384", str(caught.exception))
        self.assertEqual(self.store.docs, {})

    def test_qdrant_connection_refused_has_actionable_error_and_preserves_revisions(self):
        # Strict mode (keyword fallback disabled) keeps the original behaviour.
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"OPSLENS_PDF_BM25_FALLBACK": "false"}):
            with self.assertRaises(ingestion.PdfIndexingError) as caught:
                ingestion.ingest_pdf(b"%PDF-offline", "procedure.pdf", self.metadata, UnavailableQdrantStore())
        self.assertEqual(caught.exception.code, "qdrant_connection_refused")
        self.assertIn("Start the existing Qdrant service", str(caught.exception))
        self.assertFalse(any(Path(self.temp.name).glob("*.pdf")))

    def test_qdrant_unavailable_defaults_to_keyword_only_storage(self):
        result = ingestion.ingest_pdf(b"%PDF-offline", "procedure.pdf", self.metadata, UnavailableQdrantStore())
        self.assertEqual(result["status"], "stored_keyword_only")
        self.assertFalse(result["vector_indexed"])
        self.assertFalse(result["approved"])

    def test_revision_and_content_changes_preserve_prior_pdf_and_index(self):
        old = self.ingest(b"%PDF-old", {**self.metadata, "revision": "A"})
        new = self.ingest(b"%PDF-new", {**self.metadata, "revision": "B"})
        self.assertNotEqual(old["document_id"], new["document_id"])
        self.assertEqual(len(self.store.docs), 2)
        self.assertTrue(ingestion.get_pdf_path("SOP-TEST-01", "A", old["sha256"]).exists())
        self.assertTrue(ingestion.get_pdf_path("SOP-TEST-01", "B", new["sha256"]).exists())
        listed = ingestion.list_sop_library()
        self.assertEqual(len([doc for doc in listed if doc["storage_type"] == "local_pdf"]), 2)

    def test_failed_index_does_not_delete_or_replace_existing_revision(self):
        old = self.ingest(b"%PDF-old", {**self.metadata, "revision": "A"})
        existing_path = ingestion.get_pdf_path("SOP-TEST-01", "A", old["sha256"])
        before = existing_path.read_bytes()
        self.store.fail = True
        with self.assertRaises(ingestion.PdfIndexingError):
            self.ingest(b"%PDF-new", {**self.metadata, "revision": "B"})
        self.assertEqual(existing_path.read_bytes(), before)
        self.assertEqual(self.store.delete_calls, [])


if __name__ == "__main__":
    unittest.main()
