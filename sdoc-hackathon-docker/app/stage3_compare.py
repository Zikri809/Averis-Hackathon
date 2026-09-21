"""Deterministic SI-vs-BL comparison (plan 04).

No LLM, no I/O, no network. The only inputs are two READY ``DocRecord``s and
the output is a ``Verdict`` carrying the full defect field set plus a report.
"""
from __future__ import annotations

import re
from typing import Any

from .normalize import norm_compare
from .schema import COMPARE_FIELDS, DocRecord, FieldEvidence, Verdict
from .stage3_normalize import numeric_value, party_identity, port_name

PARTY_FIELDS = frozenset({"shipper", "consignee", "notify_party"})
PORT_FIELDS = frozenset({"port_of_loading", "port_of_discharge"})
NUMBER_FIELDS = frozenset({"container_count", "gross_weight_kg"})

ON_BEHALF_LITERAL = "ON BEHALF OF"
CHAIN_SPLIT_RX = re.compile(r"\s*\|\s*|\n|;")


def _evidence(doc: DocRecord, field_name: str) -> FieldEvidence | None:
    evidence = doc.evidence.get(field_name)
    return evidence if isinstance(evidence, FieldEvidence) else None


def _raw(doc: DocRecord, field_name: str) -> str | None:
    evidence = _evidence(doc, field_name)
    if evidence is not None and evidence.raw is not None:
        return evidence.raw
    value = doc.value(field_name)
    return None if value is None else str(value)


def _report_entry(
    si_doc: DocRecord,
    bl_doc: DocRecord,
    field_name: str,
    si_normalized: Any,
    bl_normalized: Any,
    equal: bool,
    outcome: str,
) -> dict[str, Any]:
    return {
        "si_value": si_doc.value(field_name),
        "bl_value": bl_doc.value(field_name),
        "si_normalized": si_normalized,
        "bl_normalized": bl_normalized,
        "si_raw": _raw(si_doc, field_name),
        "bl_raw": _raw(bl_doc, field_name),
        "equal": equal,
        "outcome": outcome,
    }


def _chain_contains_counterpart(raw: str | None, counterpart_identity: object) -> bool:
    """True when an ON BEHALF OF chain segment contains the full counterpart.

    Checking only literal-token segments avoids prefix matches against the
    displayed identity line, e.g. ``APRIL FINE PAPER TRADING`` vs
    ``APRIL FINE PAPER TRADING (MIDDLE EAST) FZE``.
    """
    if raw is None or ON_BEHALF_LITERAL not in raw:
        return False

    counterpart_norm = norm_compare(counterpart_identity)
    if not counterpart_norm:
        return False

    for segment in CHAIN_SPLIT_RX.split(raw):
        if ON_BEHALF_LITERAL not in segment:
            continue
        if counterpart_norm == norm_compare(segment):
            return True
        if f" {counterpart_norm} " in f" {norm_compare(segment)} ":
            return True
    return False


def _on_behalf_guard(si_doc: DocRecord, bl_doc: DocRecord, field_name: str) -> bool:
    return _chain_contains_counterpart(_raw(si_doc, field_name), bl_doc.value(field_name)) or (
        _chain_contains_counterpart(_raw(bl_doc, field_name), si_doc.value(field_name))
    )


def _normalized_pair(si_doc: DocRecord, bl_doc: DocRecord, field_name: str) -> tuple[Any, Any]:
    si_value = si_doc.value(field_name)
    bl_value = bl_doc.value(field_name)
    if field_name in PARTY_FIELDS:
        return party_identity(si_value), party_identity(bl_value)
    if field_name in PORT_FIELDS:
        return port_name(si_value), port_name(bl_value)
    if field_name in NUMBER_FIELDS:
        return numeric_value(si_value), numeric_value(bl_value)
    raise ValueError(f"unknown compare field {field_name!r}")


def compare(si_doc: DocRecord | None, bl_doc: DocRecord | None) -> Verdict:
    """Compare two READY documents and return the Stage-3 verdict."""
    diff_report: dict[str, dict] = {}

    if si_doc is None or bl_doc is None:
        return Verdict(review_reason="missing_value", diff_report=diff_report)

    defect_fields: list[str] = []
    needs_review = False

    for field_name in COMPARE_FIELDS:
        si_value = si_doc.value(field_name)
        bl_value = bl_doc.value(field_name)
        si_norm, bl_norm = _normalized_pair(si_doc, bl_doc, field_name)

        if si_value is None or bl_value is None:
            needs_review = True
            diff_report[field_name] = _report_entry(
                si_doc, bl_doc, field_name, si_norm, bl_norm, False, "missing_value"
            )
            continue

        equal = si_norm == bl_norm
        outcome = "equal"
        if not equal:
            if field_name in PARTY_FIELDS and _on_behalf_guard(si_doc, bl_doc, field_name):
                needs_review = True
                outcome = "on_behalf_of_review"
            else:
                defect_fields.append(field_name)
                outcome = "diff"

        diff_report[field_name] = _report_entry(
            si_doc, bl_doc, field_name, si_norm, bl_norm, equal, outcome
        )

    if needs_review:
        return Verdict(review_reason="missing_value", diff_report=diff_report)
    return Verdict(
        has_defect=bool(defect_fields),
        defect_fields=defect_fields,
        diff_report=diff_report,
    )
