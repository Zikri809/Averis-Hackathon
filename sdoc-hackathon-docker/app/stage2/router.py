"""Stage-2 router: extension dispatch and per-file isolation (plan 02 T3).

The router owns two contracts:

* ``register(ext, fn)`` — published here; the Binary agent calls it from
  ``binary_parsers.register_all(router)`` and never edits this file.
* ``extract_pair(email, client)`` — called by ``run.py`` (Foundation).

Until the Binary agent registers its parsers, ``.xlsx``/``.docx``/``.pdf``
route to ``NEEDS_REVIEW/unreadable`` (the W2 stub). Once they are registered,
the stub is replaced without editing this file.

Every file is parsed inside its own ``try/except``: a corrupt file becomes a
``readable: False`` document and never raises out of the orchestrator (E7).
"""
from __future__ import annotations

import re
from typing import Callable

from ..schema import COMPARE_FIELDS, DocRecord, ExtractionResult, FieldEvidence

#: ``{extension: parser(text|bytes, source_format) -> DocRecord}``.
_PARSERS: dict[str, Callable[..., DocRecord]] = {}

#: Files whose text layer exists but yields nothing are unreadable, not empty.
UNREADABLE_NOTE = "unsupported format"

#: Attachment roles come from the filename convention ``email_XXX_SI/_BL``.
ROLE_RX = re.compile(r"_(SI|BL)(?:\.[A-Za-z0-9]+)?$", re.IGNORECASE)


def register(ext: str, parser: Callable[..., DocRecord]) -> None:
    """Register a parser for an extension (``.txt``, ``.xlsx``, …)."""
    if not ext.startswith("."):
        ext = "." + ext
    _PARSERS[ext.lower()] = parser


def registered_extensions() -> tuple[str, ...]:
    return tuple(sorted(_PARSERS))


def clear_registrations() -> None:
    """Test helper: forget every registered parser."""
    _PARSERS.clear()


def attachment_role(path: str) -> str | None:
    """``"SI"``/``"BL"`` from a filename, or ``None``."""
    match = ROLE_RX.search(str(path))
    return match.group(1).upper() if match else None


def _unreadable(source_format: str, note: str = UNREADABLE_NOTE) -> DocRecord:
    fields = {field_name: None for field_name in COMPARE_FIELDS}
    evidence = {
        field_name: FieldEvidence(
            value=None,
            raw=note,
            label_found=None,
            source_format=source_format,
            confidence=0.0,
        )
        for field_name in COMPARE_FIELDS
    }
    return DocRecord(fields=fields, readable=False, source_format=source_format, evidence=evidence)


def parse_attachment(path: str, data: bytes, client) -> DocRecord:
    """Parse one attachment; never raises (E7 per-file isolation)."""
    suffix = ("." + str(path).rsplit(".", 1)[-1].lower()) if "." in str(path) else ""
    source_format = suffix.lstrip(".") or "txt"
    if source_format not in ("txt", "xlsx", "docx", "pdf", "ocr"):
        source_format = "txt"

    if not data:
        return _unreadable(source_format, "empty file")

    parser = _PARSERS.get(suffix)
    if parser is None:
        return _unreadable(source_format, UNREADABLE_NOTE)

    try:
        return parser(path, data, client)
    except Exception:
        return _unreadable(source_format, "parse failure")


def extract_pair(email: dict, client) -> ExtractionResult:
    """Parse the SI/BL pair for one email; ``NEEDS_REVIEW/unreadable`` on failure.

    The Foundation gate has already run: this is only reached for emails with
    exactly two attachments.
    """
    attachments = list(email.get("attachments") or [])
    si_path = bl_path = None
    for path in attachments:
        role = attachment_role(path)
        if role == "SI" and si_path is None:
            si_path = path
        elif role == "BL" and bl_path is None:
            bl_path = path

    # Fall back to attachment order when the filenames are unconventional.
    if si_path is None or bl_path is None:
        remaining = [p for p in attachments if p not in (si_path, bl_path)]
        if si_path is None and remaining:
            si_path = remaining.pop(0)
        if bl_path is None and remaining:
            bl_path = remaining.pop(0)

    if si_path is None or bl_path is None:
        return ExtractionResult(doc_status="NEEDS_REVIEW", review_reason="missing_attachment")

    si_doc = _read_and_parse(si_path, client)
    bl_doc = _read_and_parse(bl_path, client)

    if not si_doc.readable or not bl_doc.readable:
        return ExtractionResult(si_doc=si_doc, bl_doc=bl_doc, doc_status="NEEDS_REVIEW", review_reason="unreadable")

    from .txt_parser import missing_fields

    if missing_fields(si_doc) or missing_fields(bl_doc):
        return ExtractionResult(
            si_doc=si_doc, bl_doc=bl_doc, doc_status="NEEDS_REVIEW", review_reason="missing_value"
        )

    return ExtractionResult(si_doc=si_doc, bl_doc=bl_doc, doc_status="READY", review_reason=None)


def _read_and_parse(path: str, client) -> DocRecord:
    try:
        data = client.read_bytes(path)
    except Exception:
        suffix = ("." + str(path).rsplit(".", 1)[-1].lower()) if "." in str(path) else ""
        return _unreadable(suffix.lstrip(".") or "txt", "read failure")
    return parse_attachment(path, data, client)


def _register_text_route() -> None:
    """Self-register the ``.txt`` parser (this module owns the text route).

    The binary parsers arrive via ``binary_parsers.register_all(router)``, which
    ``run.py`` calls at W3; nothing else registers an extension.
    """
    if ".txt" in _PARSERS:
        return
    from .txt_parser import parse_text

    register(
        ".txt",
        lambda _path, data, _client: parse_text(
            data.decode("utf-8", errors="replace"), "txt"
        ),
    )


_register_text_route()
