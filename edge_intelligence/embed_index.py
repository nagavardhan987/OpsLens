"""
OpsLens - SOP Index Builder (Component 7)

Loads SOP procedure documents from `sop_documents/` and formats searchable text.
Qdrant ingestion is implemented in ingest_sops.py; this module only supplies
document loading and optional BM25 fallback data, never vector storage.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

SOP_DIR = Path(__file__).resolve().parent / "sop_documents"
INDEX_FILE = Path(__file__).resolve().parent / "sop_index.json"


def clean_text(text: str) -> str:
    """Normalize text for embedding and tokenization."""
    return re.sub(r"\s+", " ", text).strip()


def format_sop_for_indexing(sop: Dict[str, Any]) -> str:
    """
    Format full SOP content into dense semantic text for embedding and search.
    Combines title, equipment, tags, keywords, limits, and sequential steps.
    """
    lines = [
        f"Title: {sop.get('title', '')}",
        f"SOP ID: {sop.get('sop_id', '')}",
        f"Equipment: {sop.get('equipment_id', '')}",
        f"Applicable Tags: {' '.join(sop.get('tags', []))}",
        f"Keywords: {', '.join(sop.get('keywords', []))}",
    ]
    ref = sop.get("reference_limits", {})
    if ref:
        lines.append(f"Reference Limits: {json.dumps(ref)}")
    steps = sop.get("steps", [])
    if steps:
        lines.append("Procedure Steps:")
        for idx, s in enumerate(steps, start=1):
            lines.append(f"{idx}. {s}")

    return "\n".join(lines)


def load_all_sops(sop_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load all JSON SOP documents from directory."""
    target_dir = sop_dir if sop_dir is not None else SOP_DIR
    if not target_dir.exists():
        return []
    sops: List[Dict[str, Any]] = []
    for p in sorted(target_dir.glob("*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                sops.append(data)
        except Exception as e:
            print(f"Warning: Failed to load SOP file {p}: {e}")
    return sops


def build_index(
    sop_dir: Optional[Path] = None,
    output_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Build a text-only SOP manifest for optional BM25 fallback.
    """
    sops = load_all_sops(sop_dir)
    if not sops:
        raise ValueError("No SOP documents found to index.")

    target_output = output_path if output_path is not None else INDEX_FILE

    index_data: Dict[str, Any] = {
        "model": "all-MiniLM-L6-v2",
        "has_embeddings": False,
        "sops": sops,
        "texts": [format_sop_for_indexing(s) for s in sops],
        "embeddings": []
    }

    with open(target_output, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)

    print(f"SOP index written to {target_output}")
    return index_data


if __name__ == "__main__":
    build_index()
