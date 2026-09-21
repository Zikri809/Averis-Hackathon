"""Bounded one-call label fallback (plan 05 X3).

This module never creates a client and never performs network I/O by itself.
Callers pass a tiny client callable for demos/tests; under ``SCORED_RUN=1`` it
always declines.
"""
from __future__ import annotations

import json
import os
import signal
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from .. import state
from ..normalize import is_blank, norm_label, parse_count, parse_weight
from ..schema import COMPARE_FIELDS
from ..stage2.aliases import NON_COMPARE_ALIASES, canonical

THRESHOLD = 0.90
NUMBER_FIELDS = frozenset({"container_count", "gross_weight_kg"})
KNOWN_NON_FIELDS = {
    norm_label(label)
    for label in (
        "NET WEIGHT",
        "Export Carrier",
        "Freight",
        "HS Code",
        "OC No.",
        "Vessel",
        "Voyage",
        "Commodity",
        "Booking",
        "BL No.",
        "Country of Origin",
    )
}


def is_enabled() -> bool:
    return (not state.SCORED_RUN) and os.environ.get("ENABLE_LLM_LABEL_FALLBACK") == "1"


@contextmanager
def _timeout(seconds: float | None) -> Iterator[None]:
    if seconds is None or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _raise(_signum, _frame):
        raise TimeoutError("label fallback timed out")

    old_handler = signal.signal(signal.SIGALRM, _raise)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def _cache() -> dict:
    if not state.llm_cache_path().is_file():
        return {}
    try:
        data = json.loads(state.llm_cache_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict) -> None:
    state.ensure_dirs()
    state.llm_cache_path().write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def cache_key(label: str, value: Any, fields: dict[str, Any]) -> str:
    nulls = ",".join(sorted(field for field, current in fields.items() if current is None))
    return f"label-fallback::{norm_label(label)}::{str(value)}::{nulls}"


def type_compatible(field: str, value: Any, source_format: str = "txt") -> bool:
    if field not in COMPARE_FIELDS or is_blank(value):
        return False
    if field == "container_count":
        return parse_count(value) is not None
    if field == "gross_weight_kg":
        return parse_weight(value, source_format) is not None
    return True


def eligible(
    label: str,
    value: Any,
    fields: dict[str, Any],
    *,
    is_edge_case: bool = False,
    source_format: str = "txt",
) -> bool:
    normalized = norm_label(label)
    if state.SCORED_RUN or is_edge_case or not normalized:
        return False
    if canonical(label) is not None or normalized in NON_COMPARE_ALIASES or normalized in KNOWN_NON_FIELDS:
        return False
    return any(current is None and type_compatible(field, value, source_format) for field, current in fields.items())


def _parse_response(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        return None
    field = parsed.get("field")
    confidence = parsed.get("confidence")
    if field == "none":
        return {"field": "none", "confidence": float(confidence or 0.0)}
    if field not in COMPARE_FIELDS:
        return None
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        return None
    return {"field": field, "confidence": confidence}


def map_label(
    label: str,
    value: Any,
    fields: dict[str, Any],
    client: Callable[[dict[str, Any]], Any],
    *,
    is_edge_case: bool = False,
    source_format: str = "txt",
    timeout_seconds: float | None = 2.0,
) -> dict[str, Any]:
    """Return ``{"field": field|None, "confidence": float, "accepted": bool}``."""
    if not eligible(label, value, fields, is_edge_case=is_edge_case, source_format=source_format):
        return {"field": None, "confidence": 0.0, "accepted": False, "reason": "ineligible"}

    key = cache_key(label, value, fields)
    cache = _cache()
    if key in cache:
        parsed = _parse_response(cache[key])
    else:
        prompt = {
            "instruction": "Map the raw document label to one compared field or none. Reply JSON only.",
            "label": label,
            "value": value,
            "candidate_fields": [field for field, current in fields.items() if current is None],
        }
        try:
            with _timeout(timeout_seconds):
                parsed = _parse_response(client(prompt))
        except Exception:
            parsed = None
        cache[key] = parsed or {"field": "none", "confidence": 0.0}
        _save_cache(cache)

    if not parsed or parsed["field"] == "none":
        return {"field": None, "confidence": 0.0 if not parsed else parsed["confidence"], "accepted": False}
    field = str(parsed["field"])
    confidence = float(parsed["confidence"])
    accepted = (
        confidence >= THRESHOLD
        and fields.get(field) is None
        and type_compatible(field, value, source_format)
    )
    return {"field": field if accepted else None, "confidence": confidence, "accepted": accepted}
