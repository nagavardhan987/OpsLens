import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vector_store.qdrant_store import VECTOR_SIZE, validate_collection_vectors


class TestQdrantVectorValidation(unittest.TestCase):
    def test_expected_dimension_and_cosine_metric_are_accepted(self):
        validate_collection_vectors(SimpleNamespace(size=384, distance="Cosine"), "opslens_sops")

    def test_wrong_dimension_is_rejected_without_suggesting_recreation(self):
        with self.assertRaisesRegex(RuntimeError, "expected size=384, distance=cosine"):
            validate_collection_vectors(SimpleNamespace(size=768, distance="Cosine"), "opslens_sops")

    def test_wrong_distance_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "distance=dot"):
            validate_collection_vectors(SimpleNamespace(size=VECTOR_SIZE, distance="Dot"), "opslens_sops")

    def test_named_vector_schema_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "uses named vectors"):
            validate_collection_vectors({"text": SimpleNamespace(size=VECTOR_SIZE, distance="Cosine")})

    def test_unavailable_store_is_not_mistaken_for_an_empty_collection(self):
        import sop_retriever

        class OfflineStore:
            def count(self):
                return 0

            def health(self):
                return {"connected": False, "error": "connection refused"}

        previous = sop_retriever._QDRANT_STORE
        previous_attempt = sop_retriever._QDRANT_LAST_INIT_ATTEMPT
        try:
            sop_retriever._QDRANT_STORE = None
            with patch("vector_store.qdrant_store.QdrantVectorStore", return_value=OfflineStore()), \
                 patch("ingest_sops.ingest") as auto_ingest:
                self.assertIsInstance(sop_retriever.get_qdrant_store(), OfflineStore)
                auto_ingest.assert_not_called()
        finally:
            sop_retriever._QDRANT_STORE = previous
            sop_retriever._QDRANT_LAST_INIT_ATTEMPT = previous_attempt

    def test_cached_offline_store_retries_and_recovers_after_qdrant_starts(self):
        import sop_retriever

        class OfflineStore:
            def health(self):
                return {"connected": False}

        class OnlineStore:
            def health(self):
                return {"connected": True}

            def count(self):
                return 31

        previous_store = sop_retriever._QDRANT_STORE
        previous_attempt = sop_retriever._QDRANT_LAST_INIT_ATTEMPT
        try:
            sop_retriever._QDRANT_STORE = OfflineStore()
            sop_retriever._QDRANT_LAST_INIT_ATTEMPT = 0.0
            with patch("sop_retriever.time.monotonic", return_value=100.0), \
                 patch("vector_store.qdrant_store.QdrantVectorStore", return_value=OnlineStore()) as constructor:
                self.assertIsInstance(sop_retriever.get_qdrant_store(), OnlineStore)
                constructor.assert_called_once_with()
        finally:
            sop_retriever._QDRANT_STORE = previous_store
            sop_retriever._QDRANT_LAST_INIT_ATTEMPT = previous_attempt


if __name__ == "__main__":
    unittest.main()
