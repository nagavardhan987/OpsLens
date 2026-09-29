"""
OpsLens - VectorStore Abstract Interface

Defines the generic VectorStore contract.
Swap implementations (QdrantVectorStore -> FAISSVectorStore -> PineconeVectorStore)
without touching any RAG pipeline code.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class VectorStoreDocument:
    """A single SOP text chunk to be stored in the vector store."""
    def __init__(self, chunk_id: str, document_id: str, sop_id: str,
                 text: str, embedding: List[float], payload: Dict[str, Any]):
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.sop_id = sop_id
        self.text = text
        self.embedding = embedding
        self.payload = payload


class VectorSearchResult:
    """A single result returned by vector similarity search."""
    def __init__(self, chunk_id: str, sop_id: str, text: str,
                 similarity: float, payload: Dict[str, Any]):
        self.chunk_id = chunk_id
        self.sop_id = sop_id
        self.text = text
        self.similarity = similarity   # RAW cosine similarity - NOT a probability
        self.payload = payload

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.payload.get("document_id", ""),
            "document_name": self.payload.get("document_name", ""),
            "chunk_id": self.chunk_id,
            "sop_id": self.sop_id,
            "revision": self.payload.get("revision", ""),
            "source": self.payload.get("source", ""),
            "text": self.text,
            "similarity": self.similarity,
            "similarity_score": self.similarity,
            "section": self.payload.get("section", ""),
            "title": self.payload.get("title", ""),
            "equipment": self.payload.get("equipment", ""),
            "page": self.payload.get("page", 1),
        }


class VectorStore(ABC):
    """Abstract vector store interface for OpsLens RAG pipeline."""

    @abstractmethod
    def add_documents(self, documents: List[VectorStoreDocument]) -> int: ...

    @abstractmethod
    def upsert(self, documents: List[VectorStoreDocument]) -> int: ...

    @abstractmethod
    def search(self, query_vector: List[float], top_k: int = 5,
               equipment_filter: Optional[str] = None,
               plant_area_filter: Optional[str] = None) -> List[VectorSearchResult]: ...

    @abstractmethod
    def get_document(self, sop_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def delete(self, sop_id: str) -> bool: ...

    @abstractmethod
    def delete_by_document_id(self, document_id: str) -> bool: ...

    @abstractmethod
    def health(self) -> Dict[str, Any]: ...

    @abstractmethod
    def count(self) -> int: ...
