"""Stage 3 deterministic SI-vs-BL comparison.

No LLMs, no I/O, no learned state: two parsed ``DocRecord`` instances enter,
and either a comparison ``Verdict`` or a defensive ``NEEDS_REVIEW`` extraction
signal leaves.
"""
from __future__ import annotations

import re
from typing import Any

from .normalize import norm_compare
from .schema import COMPARE_FIELDS, DocRecord, ExtractionResult, Verdict
from .stage3_normalize import normalize_for_field

PARTY_FIELDS = ("shipper", "consignee", "notify_party")
ON_BEHALF_TOKEN = "ON BEHALF OF"


def compare(si_doc: DocRecord | None, bl_doc: DocRecord | None) -> Verdict | ExtractionResult:
    """Compare the seven scorer fields for one READY SI/BL pair."""
    if si_doc is None or bl_doc is None:
        return _missing_value()

    defect_fields: list[str] = []
    diff_report: dict[str, dict[str, Any]] = {}

    for field_name in COMPARE_FIELDS:
        si_raw = si_doc.value(field_name)
        bl_raw = bl_doc.value(field_name)
        si_cmp = normalize_for_field(field_name, si_raw)
        bl_cmp = normalize_for_field(field_name, bl_raw)

        if si_cmp in (None, "") or bl_cmp in (None, ""):
            return _missing_value()

        matched = si_cmp == bl_cmp
        diff_report[field_name] = {
            "si": si_raw,
            "bl": bl_raw,
            "si_normalized": si_cmp,
            "bl_normalized": bl_cmp,
            "matched": matched,
        }

        if matched:
            continue

        if field_name in PARTY_FIELDS and _on_behalf_guard(field_name, si_doc, bl_doc):
            return _missing_value()

        defect_fields.append(field_name)

    if not defect_fields:
        diff_report["_summary"] = {"message": "No mismatch detected"}

    return Verdict(
        has_defect=bool(defect_fields),
        defect_fields=defect_fields,
        diff_report=diff_report,
    )


def _missing_value() -> ExtractionResult:
    return ExtractionResult(doc_status="NEEDS_REVIEW", review_reason="missing_value")


def _on_behalf_guard(field_name: str, si_doc: DocRecord, bl_doc: DocRecord) -> bool:
    """Escalate identity mismatches when a literal chain names the counterpart."""
    si_identity = norm_compare(si_doc.value(field_name))
    bl_identity = norm_compare(bl_doc.value(field_name))
    return (
        _chain_mentions_counterpart(_evidence_raw(si_doc, field_name), bl_identity)
        or _chain_mentions_counterpart(_evidence_raw(bl_doc, field_name), si_identity)
    )


def _evidence_raw(doc: DocRecord, field_name: str) -> str:
    evidence = doc.evidence.get(field_name)
    return "" if evidence is None or evidence.raw is None else str(evidence.raw)


def _chain_mentions_counterpart(raw: str, counterpart_identity: str) -> bool:
    """True only for exact normalized chain segments after ``ON BEHALF OF``."""
    if not raw or not counterpart_identity:
        return False
    if ON_BEHALF_TOKEN not in raw.upper():
        return False

    # Preserve segment boundaries so a prefix company name does not match a
    # longer company in the chain.
    parts = [
        part.strip()
        for part in re.split(r"\s*[;|]\s*|\n", raw)
        if part.strip()
    ]
    for part in parts:
        upper_part = part.upper()
        if ON_BEHALF_TOKEN not in upper_part:
            continue
        after_token = part[upper_part.index(ON_BEHALF_TOKEN) + len(ON_BEHALF_TOKEN):]
        if norm_compare(after_token) == counterpart_identity:
            return True
    return False
