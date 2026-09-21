"""Binary parser entry point (plan 03).

The Foundation orchestrator calls :func:`register_all` at startup
(``run.py``); the router owns dispatch and never imports this module. Each
parser takes ``(path, data, client)`` and returns a :class:`DocRecord`,
never raising — corrupt/empty/image-only inputs become ``readable: False``
documents that exit ``NEEDS_REVIEW/unreadable``.
"""
from __future__ import annotations

from typing import Any

from .docx_parser import parse_docx
from .pdf_parser import parse_pdf
from .xlsx_parser import parse_xlsx

#: Extension → parser, in the order they register (informational only).
PARSERS: tuple[tuple[str, Any], ...] = (
    (".xlsx", parse_xlsx),
    (".docx", parse_docx),
    (".pdf", parse_pdf),
)


def register_all(router: Any) -> tuple[str, ...]:
    """Register every binary parser on the router; return the extensions."""
    registered: list[str] = []
    for ext, parser in PARSERS:
        router.register(ext, parser)
        registered.append(ext)
    return tuple(registered)
