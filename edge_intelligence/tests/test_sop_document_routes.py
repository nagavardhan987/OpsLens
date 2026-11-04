"""Regression coverage for reading packaged procedures without Qdrant."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.routes import _load_bundled_sop, _load_sop_document


class TestBundledSopLookup(unittest.TestCase):
    def test_bundled_document_includes_full_procedure_and_asset_metadata(self):
        document = _load_bundled_sop("SOP-P02-SEAL-01")
        self.assertIsNotNone(document)
        self.assertEqual(document["equipment_id"], "Pump-02")
        self.assertGreater(len(document["steps"]), 0)

    def test_missing_bundled_document_returns_none(self):
        self.assertIsNone(_load_bundled_sop("SOP-NOT-IN-LIBRARY"))

    def test_bundled_document_does_not_require_vector_store(self):
        def unavailable_store():
            raise AssertionError("Qdrant should not be opened for a bundled SOP")

        document = _load_sop_document("SOP-P02-SEAL-01", unavailable_store)
        self.assertEqual(document["equipment_id"], "Pump-02")
        self.assertGreater(len(document["steps"]), 0)

    def test_missing_pdf_or_bundle_returns_none_when_vector_store_is_unavailable(self):
        self.assertIsNone(_load_sop_document("SOP-NOT-IN-LIBRARY", lambda: None))

if __name__ == "__main__":
    unittest.main()
