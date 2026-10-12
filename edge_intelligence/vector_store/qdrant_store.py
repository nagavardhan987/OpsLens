"""
OpsLens - QdrantVectorStore Implementation

Primary vector store using Qdrant.
Default: local Qdrant service at http://localhost:6333.
Persistent embedded local mode is available with QDRANT_URL=embedded.

IMPORTANT: similarity scores returned are RAW cosine similarity values.
They are NOT probabilities, NOT confidence percentages.
"""
import os
import uuid
import logging
from typing import List, Dict, Any, Optional

from .base import VectorStore, VectorStoreDocument, VectorSearchResult

logger = logging.getLogger("opslens.qdrant")

COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION", "opslens_sops")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_PATH = os.environ.get("QDRANT_PATH", "./qdrant_data")
VECTOR_SIZE = 384   # all-MiniLM-L6-v2 output dimension


class QdrantVectorStore(VectorStore):
    """
    Qdrant-backed vector store for OpsLens SOP RAG pipeline.

    Defaults to a local Qdrant service. Embedded persistent mode is available
    with QDRANT_URL=embedded and stores data under QDRANT_PATH.
    """

    def __init__(self, url: Optional[str] = None, collection: str = COLLECTION_NAME):
        self.collection = collection
        self._url = url if url is not None else QDRANT_URL
        self._client = None
        self._init_client()

    def _init_client(self):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams, PayloadSchemaType

            if self._url == "embedded":
                logger.info(f"[Qdrant] Opening embedded local storage at {QDRANT_PATH}")
                self._client = QdrantClient(path=QDRANT_PATH)
            elif self._url:
                logger.info(f"[Qdrant] Connecting to remote Qdrant at {self._url}")
                self._client = QdrantClient(url=self._url)
            else:
                raise RuntimeError("Set QDRANT_URL to a local Qdrant URL or 'embedded'.")

            # Create collection if it does not exist
            existing = [c.name for c in self._client.get_collections().collections]
            if self.collection not in existing:
                self._client.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                logger.info(f"[Qdrant] Created collection '{self.collection}'")
            else:
                logger.info(f"[Qdrant] Collection '{self.collection}' already exists")

            for field in ("sop_id", "document_id", "equipment", "equipment_type", "plant_area"):
                try:
                    self._client.create_payload_index(collection_name=self.collection, field_name=field,
                                                      field_schema=PayloadSchemaType.KEYWORD)
                except Exception:
                    # Existing indexes are expected after reconnecting.
                    pass

        except ImportError:
            logger.error("[Qdrant] qdrant-client not installed. Run: pip install qdrant-client")
            self._client = None
        except Exception as e:
            logger.error(f"[Qdrant] Init failed: {e}")
            self._client = None

    def _ensure_client(self):
        if self._client is None:
            raise RuntimeError("Qdrant client not available. Check logs for details.")

    def add_documents(self, documents: List[VectorStoreDocument]) -> int:
        return self.upsert(documents)

    def upsert(self, documents: List[VectorStoreDocument]) -> int:
        self._ensure_client()
        from qdrant_client.models import PointStruct

        points = []
        for doc in documents:
            payload = dict(doc.payload)
            payload["chunk_id"] = doc.chunk_id
            payload["document_id"] = doc.document_id
            payload["sop_id"] = doc.sop_id
            payload["text"] = doc.text

            # UUID5 IDs keep upserts deterministic even for arbitrary chunk keys.
            try:
                point_id = str(uuid.UUID(doc.chunk_id))
            except (ValueError, AttributeError):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, doc.chunk_id))
            points.append(PointStruct(
                id=point_id,
                vector=doc.embedding,
                payload=payload
            ))

        self._client.upsert(collection_name=self.collection, points=points)
        logger.info(f"[Qdrant] Upserted {len(points)} chunks into '{self.collection}'")
        return len(points)

    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        equipment_filter: Optional[str] = None,
        plant_area_filter: Optional[str] = None,
    ) -> List[VectorSearchResult]:
        self._ensure_client()
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

        # Equipment aliases are a soft preference: use a Qdrant filter first,
        # then retry unfiltered when it would otherwise hide relevant content.
        aliases = []
        if equipment_filter:
            aliases = [equipment_filter]
            if "pump" in equipment_filter.lower(): aliases += ["Pump", "Pumping system"]
            if "compressor" in equipment_filter.lower(): aliases += ["Compressor"]
        conditions = []
        should = []
        if aliases:
            should.extend([
                FieldCondition(key="equipment", match=MatchAny(any=aliases)),
                FieldCondition(key="equipment_type", match=MatchAny(any=aliases)),
            ])
        if plant_area_filter:
            conditions.append(FieldCondition(key="plant_area", match=MatchValue(value=plant_area_filter)))
        query_filter = Filter(must=conditions, should=should) if conditions or should else None
        def query_points(filters=None):
            # qdrant-client 1.19 uses query_points; support older clients as
            # well so the edge deployment can pin either compatible release.
            if hasattr(self._client, "query_points"):
                response = self._client.query_points(
                    collection_name=self.collection,
                    query=query_vector,
                    query_filter=filters,
                    limit=top_k,
                    with_payload=True,
                )
                return response.points
            return self._client.search(
                collection_name=self.collection,
                query_vector=query_vector,
                query_filter=filters,
                limit=top_k,
                with_payload=True,
            )

        try:
            hits = query_points(query_filter)
        except Exception:
            hits = []
        if not hits and query_filter is not None:
            # Metadata is a retrieval preference. If it excludes all points,
            # repeat the semantic search without filters.
            hits = query_points()

        results = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(VectorSearchResult(
                chunk_id=payload.get("chunk_id", str(hit.id)),
                sop_id=payload.get("sop_id", "UNKNOWN"),
                text=payload.get("text", ""),
                similarity=round(float(hit.score), 6),   # RAW cosine similarity
                payload=payload,
            ))
        return results

    def get_document(self, sop_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve all chunks for a given sop_id and reconstruct the SOP."""
        self._ensure_client()
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        points = []
        offset = None
        while True:
            batch, next_offset = self._client.scroll(
                collection_name=self.collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="sop_id", match=MatchValue(value=sop_id))]
                ),
                limit=200,
                offset=offset,
                with_payload=True,
            )
            points.extend(batch)
            if next_offset is None:
                break
            offset = next_offset
        if not points:
            return None

        # Reconstruct SOP from chunks
        chunks = sorted(
            [p.payload for p in points],
            key=lambda x: (x.get("page", 1), x.get("chunk_number", 0), x.get("chunk_id", ""))
        )
        first = chunks[0] if chunks else {}
        return {
            "sop_id": sop_id,
            "title": first.get("title", ""),
            "equipment": first.get("equipment", ""),
            "equipment_type": first.get("equipment_type", ""),
            "plant_area": first.get("plant_area", ""),
            "revision": first.get("revision", "1.0"),
            "effective_date": first.get("effective_date", ""),
            "source": first.get("source", "OpsLens SOP Knowledge Base"),
            "source_pdf": first.get("source_pdf"),
            "page_count": first.get("page_count"),
            "keywords": first.get("keywords", []),
            "reference_limits": first.get("reference_limits", {}),
            "tags": first.get("tags", []),
            "steps": [c.get("instruction", c.get("text", "")) for c in chunks if c.get("section") == "step"],
            "content_pages": [
                {"page": page, "text": "\n\n".join(
                    c.get("text", "") for c in chunks
                    if c.get("section") == "content" and c.get("page") == page
                )}
                for page in sorted({
                    c.get("page", 1) for c in chunks if c.get("section") == "content"
                })
            ],
            "chunks": chunks,
        }

    def delete(self, sop_id: str) -> bool:
        self._ensure_client()
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        try:
            self._client.delete(
                collection_name=self.collection,
                points_selector=Filter(
                    must=[FieldCondition(key="sop_id", match=MatchValue(value=sop_id))]
                )
            )
            return True
        except Exception as e:
            logger.error(f"[Qdrant] Delete failed for sop_id={sop_id}: {e}")
            return False

    def delete_by_document_id(self, document_id: str) -> bool:
        self._ensure_client()
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        try:
            self._client.delete(collection_name=self.collection, points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]))
            return True
        except Exception as e:
            logger.error(f"[Qdrant] Delete failed for document_id={document_id}: {e}")
            return False

    def health(self) -> Dict[str, Any]:
        if self._client is None:
            return {"vector_store": "qdrant", "connected": False, "collection": self.collection,
                    "chunks": 0, "documents": 0, "error": "Client not initialised"}
        try:
            info = self._client.get_collection(self.collection)
            total_chunks = info.points_count or 0
            # Estimate unique SOPs by a quick scroll sample
            return {
                "vector_store": "qdrant",
                "mode": "embedded" if self._url == "embedded" else "local_service",
                "connected": True,
                "collection": self.collection,
                "chunks": total_chunks,
                "documents": self._unique_document_count(),
                "total_chunks": total_chunks,
                "embedding_model": "all-MiniLM-L6-v2",
                "vector_size": VECTOR_SIZE,
            }
        except Exception as e:
            return {"vector_store": "qdrant", "connected": False, "error": str(e)}

    def _unique_document_count(self) -> int:
        ids = set()
        offset = None
        while True:
            points, offset = self._client.scroll(collection_name=self.collection, limit=256,
                offset=offset, with_payload=["document_id"])
            ids.update((p.payload or {}).get("document_id") for p in points)
            if offset is None: break
        return len(ids - {None})

    def count(self) -> int:
        if self._client is None:
            return 0
        try:
            info = self._client.get_collection(self.collection)
            return info.points_count or 0
        except Exception:
            return 0
