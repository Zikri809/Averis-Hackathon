"""Review queue projection and resolution helpers (plan 05 X2)."""
from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from typing import Any

from .. import state
from ..schema import COMPARE_FIELDS, DocRecord, ExtractionResult, Verdict


def is_enabled() -> bool:
    return (not state.SCORED_RUN) and os.environ.get("ENABLE_REVIEW_QUEUE") == "1"


def _doc_items(email_id: str, reason: str, doc_name: str, doc: DocRecord | None) -> list[dict]:
    items: list[dict] = []
    if doc is None:
        return items
    for field in COMPARE_FIELDS:
        evidence = doc.evidence.get(field)
        value = doc.fields.get(field)
        if value is not None and reason == "missing_value":
            continue
        label = getattr(evidence, "label_found", None)
        raw = getattr(evidence, "raw", None)
        confidence = getattr(evidence, "confidence", None)
        items.append(
            {
                "email_id": email_id,
                "review_reason": reason,
                "document": doc_name,
                "field": field,
                "label_found": label,
                "snippet": raw if raw is not None else value,
                "confidence": confidence,
                "file_link": None,
            }
        )
    unknowns = getattr(doc, "unknown_labels", ())
    for label in unknowns:
        items.append(
            {
                "email_id": email_id,
                "review_reason": reason,
                "document": doc_name,
                "field": None,
                "label_found": label,
                "snippet": label,
                "confidence": 0.0,
                "file_link": None,
            }
        )
    return items


def from_result(
    email_id: str,
    extraction: ExtractionResult | None = None,
    verdict: Verdict | None = None,
    record: dict | None = None,
) -> list[dict]:
    if state.SCORED_RUN:
        return []
    if extraction is not None and extraction.doc_status == "NEEDS_REVIEW":
        reason = extraction.review_reason or "missing_value"
        items = _doc_items(email_id, reason, "SI", extraction.si_doc)
        items.extend(_doc_items(email_id, reason, "BL", extraction.bl_doc))
        if not items:
            items.append(
                {
                    "email_id": email_id,
                    "review_reason": reason,
                    "document": None,
                    "field": None,
                    "label_found": None,
                    "snippet": None,
                    "confidence": None,
                    "file_link": None,
                }
            )
        return items

    if verdict is not None and verdict.review_reason is not None:
        reason = verdict.review_reason
        return [
            {
                "email_id": email_id,
                "review_reason": reason,
                "document": None,
                "field": field,
                "label_found": None,
                "snippet": entry.get("si_raw") or entry.get("bl_raw"),
                "confidence": None,
                "file_link": None,
            }
            for field, entry in verdict.diff_report.items()
            if isinstance(entry, dict) and entry.get("outcome") != "equal"
        ]

    if record and record.get("status") == "NEEDS_REVIEW":
        return [
            {
                "email_id": email_id,
                "review_reason": record.get("review_reason"),
                "document": None,
                "field": None,
                "label_found": None,
                "snippet": None,
                "confidence": None,
                "file_link": None,
            }
        ]
    return []


def queue_from_submission(submission: dict[str, dict]) -> list[dict]:
    """Projection used by the HTTP server when only submission JSON is persisted."""
    if state.SCORED_RUN:
        return []
    items: list[dict] = []
    for email_id, record in sorted(submission.items()):
        if isinstance(record, dict) and record.get("status") == "NEEDS_REVIEW":
            items.extend(from_result(email_id, record=record))
    return items


def serialize(item: Any) -> dict:
    if is_dataclass(item):
        return asdict(item)
    return dict(item)
