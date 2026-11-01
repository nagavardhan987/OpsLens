import json
import unittest
from pathlib import Path

from assistant import answer_incident_question, build_assistant_response, compact_llm_context


SOP_DIR = Path(__file__).parents[1] / "sop_documents"


def load_document(sop_id):
    for path in SOP_DIR.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("sop_id") == sop_id:
            return document
    return None


def incident(sop_id="SOP-P02-VLV-01", retrieved=None, method="bm25", steps=None):
    document = load_document(sop_id)
    return {
        "event_id": "sop-test-event",
        "trigger_timestamp": "2026-10-20T10:00:00Z",
        "candidate": {"primary_tag": "VLV-04-POS", "alarm_id": "ALM-P02-HP"},
        "story": {"causal_label": "Valve position changed", "steps": []},
        "evidence": {},
        "sop_match": {
            "sop_id": sop_id,
            "sop_title": document.get("title") if document else sop_id,
            "retrieval_method": method,
            "steps": steps or [],
            "retrieved_chunks": retrieved or [],
        },
    }


class TestSopReferenceResolution(unittest.TestCase):
    def setUp(self):
        self.doc = load_document("SOP-P02-VLV-01")
        self.step = self.doc["steps"][0]
        self.chunk = {"sop_id": self.doc["sop_id"], "text": self.step,
                      "section": "step", "payload": {"sop_id": self.doc["sop_id"],
                      "text": self.step, "section": "step"}}

    def test_valid_stored_sop_step_is_resolved_with_actual_content(self):
        result = build_assistant_response(incident(retrieved=[self.chunk]), "Show SOP steps")
        source = result["sources"][0]
        self.assertTrue(source["verified"])
        self.assertFalse(source["approved"])
        self.assertIn("not verified", source["document_status"].lower())
        self.assertEqual(source["sop_id"], "SOP-P02-VLV-01")
        self.assertEqual(source["step_number"], 1)
        self.assertEqual(source["text"], self.step)
        self.assertIn("Step 1", source["section"])

    def test_unknown_sop_id_is_not_marked_verified(self):
        unknown_chunk = {"sop_id": "SOP-DOES-NOT-EXIST", "text": "A sufficiently long fake instruction."}
        result = build_assistant_response(incident("SOP-DOES-NOT-EXIST", [unknown_chunk]), "Show SOP")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["sop_resolution"]["status"], "document_not_found")
        self.assertNotIn("Verified Reference", result["answer"])

    def test_existing_document_without_matching_step_content_is_not_verified(self):
        result = build_assistant_response(incident(retrieved=[{
            "sop_id": self.doc["sop_id"], "text": "This text does not match any stored procedure step.",
            "payload": {"sop_id": self.doc["sop_id"], "text": "This text does not match any stored procedure step."},
        }]), "Show SOP")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["sop_resolution"]["status"], "document_content_unavailable")
        self.assertIn("exists", result["sop_resolution"]["message"])

    def test_empty_retrieval_has_clear_fallback_without_synthesized_reference(self):
        result = build_assistant_response(incident("SOP-NONE", []), "Show relevant SOP")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["sop_resolution"]["status"], "not_retrieved")
        self.assertIn("No applicable approved SOP passage was retrieved", result["answer"])

    def test_retrieval_unavailable_is_distinguished_from_a_successful_no_match(self):
        event = incident("SOP-NONE", [])
        event["sop_match"]["retrieval_status"] = "unavailable"
        result = build_assistant_response(event, "Show relevant SOP")
        self.assertEqual(result["sop_resolution"]["status"], "retrieval_unavailable")
        self.assertEqual(result["sources"], [])
        self.assertIn("retrieval was unavailable", result["sop_resolution"]["message"])

    def test_vector_and_keyword_retrieval_resolve_same_reference_metadata(self):
        bm25 = build_assistant_response(incident(retrieved=[self.chunk], method="bm25"), "Show SOP")
        vector = build_assistant_response(incident(retrieved=[self.chunk], method="qdrant_vector_search"), "Show SOP")
        fields = ("sop_id", "document_name", "section", "step_number", "step_title", "text", "verified", "approved")
        self.assertEqual(tuple(bm25["sources"][0][key] for key in fields),
                         tuple(vector["sources"][0][key] for key in fields))

    def test_unverified_approval_is_sent_only_as_reference_text_not_guidance(self):
        tank = load_document("SOP-T01-OVF-01")
        unapproved_doc = {**tank, "sop_id": "SOP-TEST-UNAPPROVED", "approved": False, "document_status": "Approval status not verified"}
        tank_chunk = {"sop_id": "SOP-TEST-UNAPPROVED", "text": tank["steps"][0],
                      "payload": {"sop_id": "SOP-TEST-UNAPPROVED", "text": tank["steps"][0], "section": "Step 1"}}
        event = incident("SOP-TEST-UNAPPROVED", [tank_chunk])
        result = build_assistant_response(
            event, "Show SOP",
            sop_document_loader=lambda sid: unapproved_doc if sid == "SOP-TEST-UNAPPROVED" else None,
        )
        self.assertTrue(result["sources"][0]["verified"])
        self.assertFalse(result["sources"][0]["approved"])
        compact = compact_llm_context(event, None, result)
        self.assertEqual(compact["sop_passages"][0]["text"], tank["steps"][0])
        self.assertEqual(compact["sop_passages"][0]["usage"], "reference_only_not_approved")
        self.assertEqual(compact["sop_passages"][0]["document_status"], "Approval status not verified")

    def test_demo_tank_procedure_is_source_verified_but_not_authoritatively_approved(self):
        tank = load_document("SOP-T01-OVF-01")
        tank_chunk = {
            "sop_id": tank["sop_id"],
            "text": tank["steps"][0],
            "payload": {"sop_id": tank["sop_id"], "text": tank["steps"][0], "section": "Step 1"},
        }
        event = incident(tank["sop_id"], [tank_chunk])
        result = build_assistant_response(event, "Show SOP")
        self.assertTrue(result["sources"][0]["verified"])
        self.assertFalse(result["sources"][0]["approved"])
        self.assertIn("not verified", result["sources"][0]["document_status"].lower())
        self.assertIn("Step 1", result["sources"][0]["section"])
        self.assertIn("TNK-01-LVL", result["sources"][0]["text"] + tank["steps"][1])

    def test_pdf_page_excerpt_resolves_to_stored_page_and_keeps_unverified_status(self):
        page_text = "Operators should inspect the recorded inlet pressure before taking further action. This paragraph is part of the actual PDF source page."
        excerpt = "Operators should inspect the recorded inlet pressure before taking further action."
        pdf_document = {
            "sop_id": "SOP-PDF-01", "title": "Pump pressure review", "revision": "Rev B",
            "approval_status": "unverified", "approved": False,
            "document_status": "Approval status not verified", "content_pages": [{"page": 3, "text": page_text}],
        }
        chunk = {"sop_id": "SOP-PDF-01", "text": excerpt, "page": 3,
                 "payload": {"sop_id": "SOP-PDF-01", "text": excerpt, "page": 3, "section": "content"}}
        event = incident("SOP-PDF-01", [chunk])
        result = build_assistant_response(event, "Show source", sop_document_loader=lambda _sid: pdf_document)
        source = result["sources"][0]
        self.assertTrue(source["verified"])
        self.assertFalse(source["approved"])
        self.assertEqual(source["page"], 3)
        self.assertEqual(source["text"], excerpt)

    def test_approval_requires_status_flag_and_traceable_reference(self):
        from assistant import _is_document_approved
        self.assertFalse(_is_document_approved({"approved": True, "document_status": "APPROVED"}))
        self.assertTrue(_is_document_approved({"approved": True, "approval_status": "approved", "approval_reference": "DOC-CONTROL-42"}))

    def test_unresolved_sop_clears_sources_and_never_emits_verified_reference(self):
        event = incident("SOP-NONE", [])
        result = answer_incident_question(
            event, "What is the relevant SOP section?",
            llm_complete=lambda _prompt: '{"answer":"Relevant SOP section not available in current records."}',
        )
        self.assertEqual(result["sources"], [])
        self.assertNotIn("Verified Reference", result["answer"])
        self.assertIn("not available", result["operator_response"]["bottom_line"].lower())

    def test_llm_cannot_claim_an_sop_supports_guidance_when_no_passage_was_supplied(self):
        event = incident("SOP-NONE", [])
        result = answer_incident_question(
            event, "What does the SOP say?",
            llm_complete=lambda _prompt: '{"answer":"According to the SOP, isolate the tank inlet."}',
        )
        self.assertFalse(result["llm_used"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fallback_reason"], "unretrieved_sop_instruction_claim")
        self.assertEqual(result["sources"], [])

    def test_resolved_sop_source_cannot_be_paired_with_unavailable_bottom_line(self):
        result = answer_incident_question(
            incident(retrieved=[self.chunk]), "What does the SOP say?",
            llm_complete=lambda _prompt: '{"answer":"Relevant SOP section not available in current records."}',
        )
        self.assertTrue(result["sources"])
        self.assertNotIn("not available", result["operator_response"]["bottom_line"].lower())


if __name__ == "__main__":
    unittest.main()
