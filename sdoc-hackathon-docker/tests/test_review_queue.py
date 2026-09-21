from __future__ import annotations

from app.extensions.review_queue import from_result, queue_from_submission
from app.schema import COMPARE_FIELDS, DocRecord, ExtractionResult, FieldEvidence, Verdict


def _doc(**values):
    fields = {field: values.get(field, "ok") for field in COMPARE_FIELDS}
    evidence = {
        field: FieldEvidence(value=value, raw=str(value), label_found=field, confidence=0.75)
        for field, value in fields.items()
    }
    return DocRecord(fields=fields, evidence=evidence)


def test_submission_projection_lists_needs_review():
    items = queue_from_submission(
        {
            "email_001": {"status": "OK"},
            "email_002": {"status": "NEEDS_REVIEW", "review_reason": "missing_attachment"},
        }
    )

    assert items == [
        {
            "email_id": "email_002",
            "review_reason": "missing_attachment",
            "document": None,
            "field": None,
            "label_found": None,
            "snippet": None,
            "confidence": None,
            "file_link": None,
        }
    ]


def test_missing_value_projection_includes_missing_field_evidence():
    si_doc = _doc(shipper=None)
    extraction = ExtractionResult(
        si_doc=si_doc,
        bl_doc=_doc(),
        doc_status="NEEDS_REVIEW",
        review_reason="missing_value",
    )

    items = from_result("email_010", extraction=extraction)

    assert any(item["field"] == "shipper" and item["document"] == "SI" for item in items)


def test_verdict_review_projection_uses_diff_report_snippet():
    verdict = Verdict(
        review_reason="missing_value",
        diff_report={"shipper": {"outcome": "missing_value", "si_raw": "ACME", "bl_raw": None}},
    )

    items = from_result("email_011", verdict=verdict)

    assert items[0]["snippet"] == "ACME"
