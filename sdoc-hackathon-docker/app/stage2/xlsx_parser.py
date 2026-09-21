"""``.xlsx`` SI/BL parser (plan 03 B2).

Layout (verified against every ``.xlsx`` attachment): a single sheet, col A =
label, col B = value. Title rows and noise rows (``BL INSTRUCTION``,
``so_number``…) carry no alias hit and are ignored by the shared text core —
the plan's "require an alias hit" rule falls out of exact-match lookup, no
special-casing needed.

v3-A2: weight cells are raw numbers with no unit token; the cell value keeps
its native type through synthesis only as text, and
:func:`parse_weight` accepts pure-number strings for ``xlsx``/``docx``
sources. Party cells (``"NAME | addr1; addr2"``) split on `` | `` with the
first part as identity (shared :func:`split_party`).
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

import openpyxl

from .binary_lines import render_pairs, unreadable
from .txt_parser import parse_text


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_xlsx(path: str, data: bytes, client: Any = None) -> Any:
    """Parse one ``.xlsx`` attachment into a :class:`DocRecord` (never raises)."""
    if not data:
        return unreadable("xlsx", "empty file")
    try:
        workbook = openpyxl.load_workbook(BytesIO(data), data_only=True, read_only=True)
        sheet = workbook.active
        if sheet is None:
            return unreadable("xlsx", "no worksheet")
        pairs: list[tuple[str, str]] = []
        for row in sheet.iter_rows(values_only=True):
            if not row:
                continue
            label = _cell_text(row[0])
            if not label:
                continue
            value = _cell_text(row[1]) if len(row) > 1 else ""
            pairs.append((label, value))
        workbook.close()
    except Exception:
        return unreadable("xlsx", "parse failure")
    if not pairs:
        return unreadable("xlsx", "no label rows")
    return parse_text(render_pairs(pairs), "xlsx")
