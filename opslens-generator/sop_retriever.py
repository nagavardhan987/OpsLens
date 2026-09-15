"""
OpsLens - SOP Retrieval Engine (Component 7)

Retrieves the most relevant Standard Operating Procedure (SOP) from curated
plant documents based on live incident contracts:
- Dynamic Query: constructed on-the-fly from likely_contributor_tag, primary_tag,
  and causal_label. Never hardcoded.
- Dual Retrieval: tries sentence-transformers (all-MiniLM-L6-v2) cosine similarity first,
  gracefully falling back to BM25 (rank_bm25).
- Output: strictly follows the SopMatch schema (event_id, sop_id, sop_title, match_score,
  steps, source).
- Persistence: writes to SQLite table `sop_matches`.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import numpy as np

from models import EventStory, Evidence, SopMatch
from database import Database
from embed_index import (
    load_all_sops, format_sop_for_indexing, SOP_DIR, INDEX_FILE
)


_CACHED_MODEL = None


def get_sentence_transformer():
    """Singleton getter for SentenceTransformer model."""
    global _CACHED_MODEL
    if _CACHED_MODEL is None:
        from sentence_transformers import SentenceTransformer
        try:
            _CACHED_MODEL = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
        except Exception:
            _CACHED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _CACHED_MODEL


class SopRetriever:
    """
    SOP procedure retrieval engine with semantic embedding search and BM25 fallback.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        sop_dir: Optional[Path] = None,
        index_path: Optional[Path] = None,
        force_source: Optional[str] = None
    ):
        self.db = db
        self.sop_dir = sop_dir if sop_dir is not None else SOP_DIR
        self.index_path = index_path if index_path is not None else INDEX_FILE
        self.force_source = force_source  # Can be set to 'bm25' or 'embedding' for explicit testing

        self._sops: List[Dict[str, Any]] = []
        self._doc_texts: List[str] = []
        self._embeddings: Optional[np.ndarray] = None
        self._embed_model: Any = None
        self._bm25: Any = None
        self._bm25_corpus: List[List[str]] = []

        self._load_or_build_index()

    def _load_or_build_index(self) -> None:
        """Initialize SOP documents and retrieval models."""
        self._sops = load_all_sops(self.sop_dir)
        if not self._sops:
            raise ValueError(f"No SOP documents found in {self.sop_dir}")

        self._doc_texts = [format_sop_for_indexing(s) for s in self._sops]

        # Initialize BM25 corpus
        try:
            from rank_bm25 import BM25Okapi
            self._bm25_corpus = [self._tokenize(t) for t in self._doc_texts]
            self._bm25 = BM25Okapi(self._bm25_corpus)
        except Exception as e:
            print(f"Warning: rank_bm25 not initialized: {e}")
            self._bm25 = None

        # Check if precomputed index exists
        if self.index_path.exists():
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("has_embeddings") and data.get("embeddings"):
                        self._embeddings = np.array(data["embeddings"], dtype=np.float32)
            except Exception as e:
                print(f"Warning: Failed to load precomputed index {self.index_path}: {e}")

        # Attempt to load SentenceTransformer
        try:
            self._embed_model = get_sentence_transformer()
            if self._embeddings is None:
                embs = self._embed_model.encode(self._doc_texts, convert_to_numpy=True)
                self._embeddings = embs.astype(np.float32)
        except Exception:
            self._embed_model = None

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenizer for BM25 matching."""
        return re.findall(r"[A-Za-z0-9_\-]+", text.lower())

    def build_query(
        self,
        story: Optional[EventStory] = None,
        evidence: Optional[Evidence] = None,
        primary_tag: Optional[str] = None
    ) -> str:
        """
        Build dynamic search query from live incident artifacts.
        Never uses fixed keywords.
        """
        parts: List[str] = []
        if evidence and evidence.likely_contributor_tag:
            parts.append(evidence.likely_contributor_tag)

        if primary_tag:
            parts.append(primary_tag)
        elif story and story.steps:
            # Last step represents primary trigger
            parts.append(story.steps[-1].tag)

        if story and story.causal_label:
            parts.append(story.causal_label)

        return " ".join(parts).strip()

    def _search_embedding(self, query: str) -> Optional[List[Tuple[int, float]]]:
        """Execute embedding cosine similarity search."""
        if self._embed_model is None or self._embeddings is None:
            return None

        query_emb = self._embed_model.encode([query], convert_to_numpy=True)[0].astype(np.float32)

        # Cosine similarity: (A . B) / (||A|| * ||B||)
        q_norm = np.linalg.norm(query_emb)
        if q_norm < 1e-9:
            return None

        doc_norms = np.linalg.norm(self._embeddings, axis=1)
        doc_norms = np.where(doc_norms < 1e-9, 1e-9, doc_norms)

        sims = (self._embeddings @ query_emb) / (doc_norms * q_norm)
        # Normalize to [0.0, 1.0]
        sims = np.clip(sims, 0.0, 1.0)

        results = [(idx, float(sims[idx])) for idx in range(len(self._sops))]
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _search_bm25(self, query: str) -> List[Tuple[int, float]]:
        """Execute BM25 keyword search fallback."""
        if self._bm25 is None:
            raise RuntimeError("Neither embedding model nor BM25 index is available.")

        tokens = self._tokenize(query)
        raw_scores = self._bm25.get_scores(tokens)

        # Normalize BM25 scores to [0.0, 1.0]
        max_score = float(np.max(raw_scores)) if len(raw_scores) > 0 else 0.0
        if max_score > 1e-9:
            normalized = [float(s / (max_score * 1.15)) for s in raw_scores]
        else:
            normalized = [0.0 for _ in raw_scores]

        results = [(idx, min(1.0, max(0.0, round(normalized[idx], 4)))) for idx in range(len(self._sops))]
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def retrieve(
        self,
        story: Optional[EventStory] = None,
        evidence: Optional[Evidence] = None,
        primary_tag: Optional[str] = None,
        custom_query: Optional[str] = None,
        persist: bool = True
    ) -> SopMatch:
        """
        Retrieve best matching SOP for the given live incident.
        1. Assembles dynamic query string.
        2. Tries embedding search, falls back to BM25.
        3. Returns SopMatch contract.
        4. Persists to SQLite table `sop_matches`.
        """
        event_id = story.event_id if story else (evidence.event_id if evidence else "unknown-event")
        query = custom_query if custom_query is not None else self.build_query(story, evidence, primary_tag)

        ranked: Optional[List[Tuple[int, float]]] = None
        source: str = "bm25"

        # Check if forced source or try embedding first
        if self.force_source == "bm25":
            ranked = self._search_bm25(query)
            source = "bm25"
        elif self.force_source == "embedding":
            ranked = self._search_embedding(query)
            if ranked is None:
                ranked = self._search_bm25(query)
                source = "bm25"
            else:
                source = "embedding"
        else:
            # Default: try embedding first, then fallback to BM25
            try:
                ranked = self._search_embedding(query)
                if ranked is not None:
                    source = "embedding"
                else:
                    ranked = self._search_bm25(query)
                    source = "bm25"
            except Exception:
                ranked = self._search_bm25(query)
                source = "bm25"

        top_idx, top_score = ranked[0]
        matched_sop = self._sops[top_idx]

        match = SopMatch(
            event_id=event_id,
            sop_id=matched_sop.get("sop_id", "UNKNOWN-SOP"),
            sop_title=matched_sop.get("title", "Unknown SOP"),
            match_score=round(top_score, 4),
            steps=matched_sop.get("steps", []),
            source=source
        )

        if persist and self.db:
            self.db.save_sop_match(match)

        return match

    def get_all_ranked_scores(
        self,
        query: str,
        source_override: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Utility for inspecting discrimination scores across all documents."""
        src = source_override if source_override is not None else self.force_source
        if src == "embedding":
            ranked = self._search_embedding(query)
            actual_src = "embedding" if ranked is not None else "bm25"
            if ranked is None:
                ranked = self._search_bm25(query)
        else:
            try:
                ranked = self._search_embedding(query)
                actual_src = "embedding" if ranked is not None else "bm25"
                if ranked is None:
                    ranked = self._search_bm25(query)
            except Exception:
                ranked = self._search_bm25(query)
                actual_src = "bm25"

        return [
            {
                "sop_id": self._sops[idx]["sop_id"],
                "title": self._sops[idx]["title"],
                "score": score,
                "source": actual_src
            }
            for idx, score in ranked
        ]
