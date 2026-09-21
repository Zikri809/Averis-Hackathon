"""Record shapes and the submission contract (plan 00, F1).

This module is the single source of truth for record shapes: every stage
imports it, no stage redefines a record. Any shape change is a Foundation
task and bumps ``SCHEMA_VERSION``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "3.0"

#: The 7 compared fields, in scorer order.
COMPARE_FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]

#: Exact scorer vocabulary (server/scoring.py).
CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
STATUSES = ["OK", "MISMATCH", "NEEDS_REVIEW"]
REVIEW_REASONS = ["wrong_doc_type", "missing_attachment", "unreadable", "missing_value"]

#: Required submission keys, in sample_submission.json order.
SUBMISSION_KEYS = ("category", "status", "review_reason", "defect_fields", "has_defect")
#: Optional keys that may be added but must never replace a required key.
OPTIONAL_SUBMISSION_KEYS = ("decided_by",)

SOURCE_FORMATS = ("txt", "xlsx", "docx", "pdf", "ocr")
DOC_STATUSES = ("READY", "NEEDS_REVIEW")

NUMBER = (int, float)


@dataclass
class FieldEvidence:
    """Provenance for one extracted field (display-only confidence)."""

    value: str | int | float | None = None
    raw: str | None = None
    label_found: str | None = None
    source_format: str = "txt"
    confidence: float = 1.0


@dataclass
class DocRecord:
    """One parsed document; ``fields`` carries exactly ``COMPARE_FIELDS``."""

    fields: dict[str, str | int | float | None]
    readable: bool = True
    source_format: str = "txt"
    evidence: dict[str, FieldEvidence] = field(default_factory=dict)

    def __post_init__(self) -> None:
        expected = set(COMPARE_FIELDS)
        keys = set(self.fields)
        if keys != expected:
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            raise ValueError(
                f"DocRecord.fields must be exactly COMPARE_FIELDS "
                f"(missing={missing}, extra={extra})"
            )
        if self.source_format not in SOURCE_FORMATS:
            raise ValueError(f"unknown source_format {self.source_format!r}")

    def value(self, field_name: str) -> str | int | float | None:
        return self.fields.get(field_name)


@dataclass
class ExtractionResult:
    """Stage-2 outcome for one email."""

    si_doc: DocRecord | None = None
    bl_doc: DocRecord | None = None
    doc_status: str = "READY"
    review_reason: str | None = None

    def __post_init__(self) -> None:
        if self.doc_status not in DOC_STATUSES:
            raise ValueError(f"doc_status must be one of {DOC_STATUSES}, got {self.doc_status!r}")
        if self.doc_status == "NEEDS_REVIEW":
            if self.review_reason not in REVIEW_REASONS:
                raise ValueError(
                    f"NEEDS_REVIEW requires a review_reason in {REVIEW_REASONS}, "
                    f"got {self.review_reason!r}"
                )
        elif self.review_reason is not None:
            raise ValueError("READY extraction must not carry a review_reason")

    @property
    def ready(self) -> bool:
        return self.doc_status == "READY"

    @property
    def has_docs(self) -> bool:
        return self.si_doc is not None and self.bl_doc is not None


@dataclass
class Verdict:
    """Stage-3 outcome for one READY pair."""

    has_defect: bool = False
    defect_fields: list[str] = field(default_factory=list)
    diff_report: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = [f for f in self.defect_fields if f not in COMPARE_FIELDS]
        if unknown:
            raise ValueError(f"defect_fields contains unknown fields: {unknown}")
        if bool(self.defect_fields) != bool(self.has_defect):
            raise ValueError(
                "has_defect must equal bool(defect_fields): "
                f"has_defect={self.has_defect}, defect_fields={self.defect_fields}"
            )


def default_submission_record(category: str = "GENERAL") -> dict[str, Any]:
    """The baseline record: ``GENERAL``/``OK`` (category overrideable)."""
    return submission_record(category=category)


def submission_record(
    category: str = "GENERAL",
    status: str = "OK",
    review_reason: str | None = None,
    defect_fields: list[str] | None = None,
    has_defect: bool = False,
    decided_by: str | None = None,
) -> dict[str, Any]:
    """Build a submission record with the exact scorer keys."""
    record: dict[str, Any] = {
        "category": category,
        "status": status,
        "review_reason": review_reason,
        "defect_fields": list(defect_fields or []),
        "has_defect": has_defect,
    }
    if decided_by is not None:
        record["decided_by"] = decided_by
    return record


def validate_submission_record(record: Any) -> list[str]:
    """Return a list of contract violations (empty list = valid)."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return [f"record must be a dict, got {type(record).__name__}"]

    missing = [k for k in SUBMISSION_KEYS if k not in record]
    if missing:
        errors.append(f"missing required keys: {missing}")
    extra = [k for k in record if k not in SUBMISSION_KEYS and k not in OPTIONAL_SUBMISSION_KEYS]
    if extra:
        errors.append(f"unknown keys: {extra}")

    category = record.get("category")
    if category not in CATEGORIES:
        errors.append(f"category must be one of {CATEGORIES}, got {category!r}")

    status = record.get("status")
    if status not in STATUSES:
        errors.append(f"status must be one of {STATUSES}, got {status!r}")

    review_reason = record.get("review_reason")
    if review_reason is not None and review_reason not in REVIEW_REASONS:
        errors.append(
            f"review_reason must be null or one of {REVIEW_REASONS}, got {review_reason!r}"
        )

    defect_fields = record.get("defect_fields")
    if not isinstance(defect_fields, list):
        errors.append(f"defect_fields must be a list, got {type(defect_fields).__name__}")
    else:
        unknown = [f for f in defect_fields if f not in COMPARE_FIELDS]
        if unknown:
            errors.append(f"defect_fields contains unknown fields: {unknown}")

    has_defect = record.get("has_defect")
    if not isinstance(has_defect, bool):
        errors.append(f"has_defect must be a bool, got {type(has_defect).__name__}")
    elif has_defect != (status == "MISMATCH"):
        errors.append(
            f"has_defect must equal (status == 'MISMATCH'): "
            f"status={status!r}, has_defect={has_defect!r}"
        )

    if status == "MISMATCH" and not defect_fields:
        errors.append("MISMATCH requires at least one defect field")
    if status != "MISMATCH" and defect_fields:
        errors.append("defect_fields must be empty unless status == 'MISMATCH'")
    if status == "NEEDS_REVIEW" and review_reason is None:
        errors.append("NEEDS_REVIEW requires a review_reason")
    if status != "NEEDS_REVIEW" and review_reason is not None:
        errors.append("review_reason must be null unless status == 'NEEDS_REVIEW'")

    decided_by = record.get("decided_by")
    if decided_by is not None and decided_by not in ("rule", "sim", "llm"):
        errors.append(f"decided_by must be rule/sim/llm, got {decided_by!r}")

    return errors
