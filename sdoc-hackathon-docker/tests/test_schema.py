"""Contract test — record shapes and the submission key set (plan 00 F1)."""
from __future__ import annotations

import pytest

from app import schema


def test_schema_version_exported():
    assert schema.SCHEMA_VERSION == "3.0"


def test_compare_fields_order_and_length():
    assert schema.COMPARE_FIELDS == [
        "shipper",
        "consignee",
        "notify_party",
        "port_of_loading",
        "port_of_discharge",
        "container_count",
        "gross_weight_kg",
    ]
    assert len(schema.COMPARE_FIELDS) == 7


def test_submission_keys_exact():
    record = schema.submission_record()
    assert tuple(record) == schema.SUBMISSION_KEYS
    assert set(record) == {
        "category",
        "status",
        "review_reason",
        "defect_fields",
        "has_defect",
    }


def test_default_record_is_general_ok():
    record = schema.default_submission_record()
    assert record["category"] == "GENERAL"
    assert record["status"] == "OK"
    assert record["review_reason"] is None
    assert record["defect_fields"] == []
    assert record["has_defect"] is False
    assert schema.validate_submission_record(record) == []


def test_decided_by_is_optional_and_validated():
    record = schema.submission_record(decided_by="rule")
    assert record["decided_by"] == "rule"
    assert schema.validate_submission_record(record) == []
    assert schema.validate_submission_record(schema.submission_record(decided_by="guess"))


def test_doc_record_requires_exact_compare_fields():
    fields = {name: None for name in schema.COMPARE_FIELDS}
    doc = schema.DocRecord(fields=fields)
    assert doc.readable is True
    with pytest.raises(ValueError):
        schema.DocRecord(fields={"shipper": "X"})
    extra = dict(fields, vessel="X")
    with pytest.raises(ValueError):
        schema.DocRecord(fields=extra)


def test_doc_record_rejects_unknown_source_format():
    fields = {name: None for name in schema.COMPARE_FIELDS}
    with pytest.raises(ValueError):
        schema.DocRecord(fields=fields, source_format="rtf")


def test_extraction_result_contract():
    ready = schema.ExtractionResult()
    assert ready.ready and not ready.has_docs
    review = schema.ExtractionResult(doc_status="NEEDS_REVIEW", review_reason="unreadable")
    assert not review.ready
    with pytest.raises(ValueError):
        schema.ExtractionResult(doc_status="NEEDS_REVIEW", review_reason=None)
    with pytest.raises(ValueError):
        schema.ExtractionResult(doc_status="READY", review_reason="unreadable")
    with pytest.raises(ValueError):
        schema.ExtractionResult(doc_status="NEEDS_REVIEW", review_reason="made_up")


def test_verdict_invariants():
    clean = schema.Verdict()
    assert clean.has_defect is False and clean.defect_fields == []
    defect = schema.Verdict(has_defect=True, defect_fields=["consignee"])
    assert defect.has_defect
    with pytest.raises(ValueError):
        schema.Verdict(has_defect=True, defect_fields=[])
    with pytest.raises(ValueError):
        schema.Verdict(has_defect=False, defect_fields=["consignee"])
    with pytest.raises(ValueError):
        schema.Verdict(has_defect=True, defect_fields=["vessel"])


def test_validate_submission_record_flags_violations():
    bad = {
        "category": "NOPE",
        "status": "MISMATCH",
        "review_reason": "unreadable",
        "defect_fields": ["vessel"],
        "has_defect": False,
    }
    problems = schema.validate_submission_record(bad)
    assert any("category" in p for p in problems)
    assert any("review_reason" in p for p in problems)
    assert any("defect_fields" in p for p in problems)
    assert any("has_defect" in p for p in problems)


def test_validate_submission_record_flags_missing_keys():
    problems = schema.validate_submission_record({"category": "GENERAL", "status": "OK"})
    assert any("missing required keys" in p for p in problems)
