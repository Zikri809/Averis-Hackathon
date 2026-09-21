"""Comparison-side normalization for Stage 3.

Stage 2 canonicalizes labels and typed values; this module owns only the
normalization needed to decide equality between two READY document records.
"""
from __future__ import annotations

import re

from .normalize import norm_compare

_PAREN = re.compile(r"\([^)]*\)")
_LOCODE = re.compile(r"\s*\([A-Z]{5}\)\s*$")


def normalize_party(value: object) -> str:
    """Party identity equality: punctuation/case/whitespace insensitive."""
    return norm_compare(value)


def normalize_port(value: object) -> str:
    """Port equality compares the name only, never the LOCODE.

    Stage 2 usually removes the trailing LOCODE already, but Stage 3 strips it
    defensively and also removes qualifiers such as ``(WESTPORT)`` before the
    standard comparison normalization.
    """
    if value is None:
        return ""
    text = _LOCODE.sub("", str(value))
    text = _PAREN.sub(" ", text)
    return norm_compare(text)


def normalize_number(value: object) -> int | float | None:
    """Numeric comparison value with comma-only formatting absorbed."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def normalize_for_field(field_name: str, value: object) -> object:
    """Return the value used for exact Stage-3 equality."""
    if field_name in ("shipper", "consignee", "notify_party"):
        return normalize_party(value)
    if field_name in ("port_of_loading", "port_of_discharge"):
        return normalize_port(value)
    if field_name in ("container_count", "gross_weight_kg"):
        return normalize_number(value)
    return value
