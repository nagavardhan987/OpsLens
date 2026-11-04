"""Verified source page ranges for the 12 procedures in the bundled draft manual."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


DEMO_SOP_SECTIONS = {
    "SOP-GEN-001": {"pages": (4, 5, 6, 7), "plant_area": "All areas"},
    # Section runs onto page 8 (steps 8-9, Emergency, Records).
    "SOP-GEN-002": {"pages": (6, 7, 8), "plant_area": "Wet well, tanks, digester"},
    "SOP-GEN-003": {"pages": (8, 9), "plant_area": "Control room"},
    "SOP-GEN-004": {"pages": (9, 10), "plant_area": "All areas"},
    "SOP-INL-001": {"pages": (10, 11, 12), "plant_area": "Inlet works"},
    "SOP-LFT-001": {"pages": (12, 13, 14, 15), "plant_area": "Lift station and wet well"},
    "SOP-GEN-005": {"pages": (15, 16), "plant_area": "All areas, gas area"},
    "SOP-BIO-001": {"pages": (16, 17, 18), "plant_area": "Aeration tanks"},
    "SOP-BIO-002": {"pages": (18, 19, 20), "plant_area": "Secondary clarifiers, RAS pumps"},
    "SOP-GAS-001": {"pages": (21, 22, 23), "plant_area": "Gas line"},
    "SOP-SLD-001": {"pages": (23, 24, 25, 26), "plant_area": "Sludge line"},
    "SOP-LAB-001": {"pages": (26,), "plant_area": "Laboratory"},
}


def load_demo_sop_document(sop_id: str) -> Optional[dict]:
    """Extract the actual source pages for a named procedure without creating text."""
    section = DEMO_SOP_SECTIONS.get(sop_id)
    if not section:
        return None
    try:
        from pdf_sop_ingestion import PDF_DIR, get_pdf_path
        metadata = None
        for metadata_path in PDF_DIR.glob("*.json"):
            try:
                candidate = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if candidate.get("sop_id") == "SOP-MAN-000":
                metadata = candidate
                break
        if not metadata:
            return None
        entry = next((row for row in metadata.get("sop_register", []) if row.get("sop_id") == sop_id), None)
        if not entry:
            return None
        import fitz
        pdf_path = get_pdf_path("SOP-MAN-000", metadata.get("revision", ""), metadata.get("sha256", ""))
        with fitz.open(pdf_path) as pdf:
            page_texts = [page.get_text("text").strip() for page in pdf]
            # Bound each procedure by its actual title heading and the next SOP
            # title. This excludes adjacent procedures that share a PDF page.
            heading = re.compile(r"(?m)^(SOP-[A-Z]{3}-\d{3})\s*:\s*[^\n]+")
            offsets = []
            cursor = 0
            for page_number, text in enumerate(page_texts, start=1):
                offsets.append((cursor, cursor + len(text), page_number, text))
                cursor += len(text) + 1
            manual_text = "\n".join(page_texts)
            headings = list(heading.finditer(manual_text))
            selected = next((index for index, item in enumerate(headings) if item.group(1) == sop_id), None)
            pages = []
            if selected is not None:
                start = headings[selected].start()
                end = headings[selected + 1].start() if selected + 1 < len(headings) else len(manual_text)
                first_page, last_page = min(section["pages"]), max(section["pages"])
                for page_start, page_end, page_number, text in offsets:
                    if page_number < first_page or page_number > last_page:
                        continue
                    overlap_start, overlap_end = max(start, page_start), min(end, page_end)
                    if overlap_start < overlap_end:
                        excerpt = manual_text[overlap_start:overlap_end].strip()
                        if excerpt:
                            pages.append({"page": page_number, "text": excerpt})
            if not pages:
                pages = [{"page": index, "text": page_texts[index - 1]}
                         for index in section["pages"] if 0 < index <= len(page_texts)]
        if not pages or not any(page["text"] for page in pages):
            return None
        return {
            **metadata,
            "sop_id": sop_id,
            "title": entry["title"],
            "equipment": entry.get("process_area") or section["plant_area"],
            "equipment_type": "Wastewater Treatment",
            "plant_area": section["plant_area"],
            "applicable_equipment_ids": [section["plant_area"]],
            "revision": metadata.get("revision", "0"),
            "revision_label": metadata.get("revision_label", "0 (Draft for review)"),
            "approval_status": metadata.get("approval_status", "draft"),
            "approved": False,
            "document_status": metadata.get("document_status", "Reference only — not an approved plant SOP."),
            "manual_review_required": True,
            "source_pages": [page["page"] for page in pages],
            "content_pages": pages,
        }
    except Exception:
        return None
