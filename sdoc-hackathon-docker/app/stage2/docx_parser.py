"""``.docx`` SI/BL parser (plan 03 B3).

Layout (verified against every ``.docx`` attachment): heading paragraphs
(``BILL OF LADING (DRAFT)``, ``B/L NO.…``, ``ORDER NO.…`` — doc-type evidence,
never compared fields) plus exactly one 2-column table. Cell[0] is the label,
which may carry a CJK parenthetical suffix (``Shipper (Principal or Seller)
(发货人)``); the shared normalizer strips parentheticals before lookup.
Cell[1] holds ``name\\naddr\\naddr`` — the first non-empty line is the
identity, the rest render as indented continuations.

v3-A2: weights render as ``f"{weight:,}"`` with no unit (``243,588``); the
pure-number string rule accepts them as KG.
"""
from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import docx

from .binary_lines import render_pairs, unreadable
from .txt_parser import parse_text

#: Bilingual suffixes, e.g. ``Notify Party/Intermediate Consignee (通知人)``.
#: The shared normalizer strips parentheticals for lookup, but the label
#: regex caps labels at 40 chars — so CJK suffixes are stripped here first.
#: ASCII-only parens (``(POL)``, ``(kgs)``) are kept: they fit and lookup
#: handles them.
_CJK_PAREN_RX = re.compile(r"\s*\([^)]*[^\x00-\x7F][^)]*\)")


#: The shared label regex caps labels at 40 chars (:mod:`txt_parser`); longer
#: bilingual labels are shortened here, shorter ones keep their raw form so
#: evidence shows the original document label.
_LABEL_LEN_CAP = 40


def _strip_bilingual(label: str) -> str:
    return _CJK_PAREN_RX.sub("", label).strip()


def parse_docx(path: str, data: bytes, client: Any = None) -> Any:
    """Parse one ``.docx`` attachment into a :class:`DocRecord` (never raises)."""
    if not data:
        return unreadable("docx", "empty file")
    try:
        document = docx.Document(BytesIO(data))
    except Exception:
        return unreadable("docx", "parse failure")
    pairs: list[tuple[str, str]] = []
    for table in document.tables:
        for row in table.rows:
            cells = row.cells
            if len(cells) < 2:
                continue
            label = cells[0].text.strip()
            if len(label) > _LABEL_LEN_CAP:
                label = _strip_bilingual(label)
            if not label:
                continue
            pairs.append((label, cells[1].text.strip()))
    if not pairs:
        return unreadable("docx", "no label rows")
    return parse_text(render_pairs(pairs), "docx")
