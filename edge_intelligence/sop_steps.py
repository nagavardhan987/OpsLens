"""
OpsLens - Verbatim procedure-step extraction from SOP source pages.

Guidance must never invent procedural steps. This module reads the text that
was extracted from the SOP PDF and returns the numbered steps of a
"Procedure" section exactly as written (only line-wrapping is joined), with
the page each step starts on. If no numbered procedure can be found, it
returns an empty list and callers fall back to "Operator verification
required".
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

_FOOTER = re.compile(r"^(SOP Manual\s+[–-].*|Page \d+ of \d+)$", re.IGNORECASE)
_NUMBERED = re.compile(r"^\s*(\d{1,2})\.\s+(.*\S)\s*$")
_SECTION_WORDS = (
    "escalation", "records", "preventive", "special rules", "emergency", "required",
    "scope", "purpose", "responsibilities", "operating limits", "hazards", "schedule",
    "acceptable atmosphere", "routine operation",
)
# Table headers that PDF text extraction can interleave with procedure text
# when a limits table continues on the same page.
_TABLE_HEADERS = ("parameter", "sample point", "term ", "role ", "priority ", "area ", "field ")
_RESPONSE_WORDS = ("response", "abnormal", "high", "trip", "failure", "blockage", "alarm", "clog")


def _is_section_heading(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered.startswith("procedure"):
        return True
    return any(lowered.startswith(word) for word in _SECTION_WORDS) and len(lowered) < 60


def _clean_lines(pages: Iterable[Dict[str, Any]]):
    for page in pages:
        number = page.get("page")
        for raw in str(page.get("text") or "").splitlines():
            line = raw.strip()
            if not line or _FOOTER.match(line):
                continue
            yield number, line


def extract_procedures(pages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return every numbered procedure section found in the pages."""
    procedures: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    expected = 1
    skipping_table = False
    for page_number, line in _clean_lines(pages):
        numbered = _NUMBERED.match(line)
        if numbered and _is_section_heading(numbered.group(2)):
            heading = numbered.group(2)
            if heading.lower().startswith("procedure"):
                current = {"procedure_title": heading, "page": page_number, "steps": []}
                procedures.append(current)
                expected = 1
            else:
                current = None
            continue
        if current is None:
            continue
        if numbered and int(numbered.group(1)) == expected:
            current["steps"].append({"number": expected, "text": numbered.group(2), "page": page_number})
            expected += 1
            skipping_table = False
            continue
        if numbered:
            # A number out of sequence is the next section ("7. Escalation").
            current = None
            continue
        lowered_line = line.lower()
        if lowered_line.startswith(_TABLE_HEADERS) or lowered_line.strip() in {h.strip() for h in _TABLE_HEADERS}:
            # Interleaved table text: ignore until the next numbered step.
            skipping_table = True
            continue
        if current["steps"] and not skipping_table:
            # Wrapped continuation of the previous step.
            current["steps"][-1]["text"] += " " + line
    return [p for p in procedures if p["steps"]]


def select_procedure(procedures: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Prefer an abnormal-condition/response procedure over start-up/routine."""
    if not procedures:
        return None
    for procedure in procedures:
        title = procedure["procedure_title"].lower()
        if any(word in title for word in _RESPONSE_WORDS):
            return procedure
    return procedures[0]


def procedure_steps_for_document(document: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Steps for a document returned by demo_sop_sections.load_demo_sop_document."""
    if not document:
        return {"procedure_title": None, "steps": [], "source": "unavailable"}
    pages = document.get("content_pages") or []
    selected = select_procedure(extract_procedures(pages))
    if not selected:
        return {"procedure_title": None, "steps": [], "source": "no_numbered_procedure_found"}
    return {
        "procedure_title": selected["procedure_title"],
        "steps": selected["steps"],
        "source": "verbatim_pdf_text",
        "sop_id": document.get("sop_id"),
        "source_pdf": document.get("source_pdf"),
    }


def procedure_steps(sop_id: str) -> Dict[str, Any]:
    try:
        from demo_sop_sections import load_demo_sop_document
        document = load_demo_sop_document(sop_id)
    except Exception:
        document = None
    result = procedure_steps_for_document(document)
    result.setdefault("sop_id", sop_id)
    return result
