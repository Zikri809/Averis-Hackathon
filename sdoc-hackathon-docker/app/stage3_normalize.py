"""Comparison-side normalization for Stage 3 (plan 04).

This module is intentionally small and deterministic. It wraps Foundation's
``norm_compare`` with the few field-specific comparison rules owned by Stage 3.
"""
from __future__ import annotations

import re

from .normalize import norm_compare

LOCODE_TRAILER_RX = re.compile(r"\s*\(([A-Z]{5})\)\s*$")
PAREN_QUALIFIER_RX = re.compile(r"\([^)]*\)")


def party_identity(value: object) -> str:
    """Normalize a party identity for exact equality."""
    return norm_compare(value)


def port_name(value: object) -> str:
    """Normalize a port by name only; LOCODEs and qualifiers do not compare."""
    text = "" if value is None else str(value)
    text = LOCODE_TRAILER_RX.sub("", text).strip()
    text = PAREN_QUALIFIER_RX.sub(" ", text)
    return norm_compare(text)


def numeric_value(value: object) -> int | float | None:
    """Return the typed numeric value Stage 2 produced."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None
