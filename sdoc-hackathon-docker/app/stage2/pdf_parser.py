"""``.pdf`` SI/BL parser (plan 03 B4/B5/B6).

Text-layer geometry (verified against all 28 ``.pdf`` attachments, one page
each): field labels sit at x≈57, values at x≈170. pymupdf splits same-baseline
spans into separate line objects, so pairing is by baseline proximity: a
label-column line followed by a value-column line within ~2pt vertically is
one ``label: value`` row; value-column lines further below are continuations
(address chains, ``ON BEHALF OF`` blocks). The container table
(``CONTAINER NO. / DESCRIPTION / GROSS WEIGHT (KG)`` + one row per container)
shares the page but its cells never pair into a compared field — unknown
labels are recorded and ignored, and the weight anchor is the
``TOTAL``-prefixed summary line only ("next span below" fallback is
forbidden: it would grab a container weight).

v3-A3/B5: the ``TOTAL`` line joins its spans before matching
(``TOTAL Gross Weight`` + ``II`` + ``(KGS): 117,770 KG``); any
``TOTAL * GROSS WEIGHT|WT *`` label rewrites to the ``Gross Weight`` alias.
``.pdf`` weight strings still require the ``KG`` marker (v3-A2 text rule).

Image-only pages (no text layer, embedded image) and corrupt/encrypted files
return ``readable: False`` (E5; OCR stays demo-only, never scored).
"""
from __future__ import annotations

import re
from typing import Any

try:
    import pymupdf
except ImportError:  # pragma: no cover - pymupdf always ships the fitz shim
    import fitz as pymupdf

from ..normalize import norm_label
from .aliases import canonical, is_known_non_compare
from .binary_lines import render_pairs, unreadable
from .txt_parser import LABEL_RX, parse_text

#: Spans starting left of this x are label-column candidates (labels sit at
#: x≈57, values at x≈170, table mid/right columns at x≈198/397).
LABEL_COL_X = 120.0

#: Max vertical gap (points) for pairing a label line with its value line.
BASELINE_TOLERANCE = 3.0

#: ``TOTAL Gross WeightII(KGS)`` / ``TOTAL Gross Wt (kgs)`` / … → weight.
_TOTAL_RX = re.compile(r"^TOTAL\b.*\bGROSS\s+(WEIGHT|WT)\b")


def _is_total_weight(label_text: str) -> bool:
    return _TOTAL_RX.search(norm_label(label_text)) is not None


def _is_compared(label_text: str) -> bool:
    return canonical(label_text) is not None


def _is_known_label(label_text: str) -> bool:
    return (
        _is_compared(label_text)
        or is_known_non_compare(label_text) is not None
        or _is_total_weight(label_text)
    )


def _rewrite_total(label_text: str) -> str:
    """Map any TOTAL-prefixed weight label onto the ``Gross Weight`` alias."""
    if _is_total_weight(label_text):
        return "Gross Weight"
    return label_text


def _split_colon(text: str) -> tuple[str, str] | None:
    """Split a ``Label: value`` line like the shared label regex does."""
    match = LABEL_RX.match(text.strip())
    if match is None:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _page_lines(page: Any) -> tuple[list[tuple[float, list[tuple[float, str]]]], bool]:
    """Flatten one page to ``(y, [(x0, text), …])`` lines; report images."""
    flat: list[tuple[float, list[tuple[float, str]]]] = []
    for block in page.get_text("dict").get("blocks", ()):
        if block.get("type", 1) != 0:
            continue
        for line in block.get("lines", ()):
            spans = [
                (span["bbox"][0], str(span.get("text") or "").strip())
                for span in line.get("spans", ())
                if str(span.get("text") or "").strip()
            ]
            if not spans:
                continue
            spans.sort(key=lambda item: item[0])
            flat.append((line["bbox"][1], spans))
    try:
        has_images = bool(page.get_images())
    except Exception:
        has_images = False
    return flat, has_images


def parse_pdf(path: str, data: bytes, client: Any = None) -> Any:
    """Parse one ``.pdf`` attachment into a :class:`DocRecord` (never raises)."""
    if not data:
        return unreadable("pdf", "empty file")
    try:
        doc = pymupdf.open(stream=bytes(data), filetype="pdf")
    except Exception:
        return unreadable("pdf", "parse failure")
    try:
        if getattr(doc, "needs_pass", False):
            return unreadable("pdf", "encrypted")
        # Phase 1: rows are (label, value); label None = continuation/stray.
        rows: list[tuple[str | None, str, float]] = []
        text_chars = 0
        has_images = False
        for page in doc:
            try:
                flat, page_images = _page_lines(page)
            except Exception:
                continue
            has_images = has_images or page_images
            text_chars += sum(len(text) for _, spans in flat for _, text in spans)
            index = 0
            while index < len(flat):
                y, spans = flat[index]
                x0, text = spans[0]
                nxt = flat[index + 1] if index + 1 < len(flat) else None
                if len(spans) > 1 and x0 < LABEL_COL_X:
                    # Label + value share one line object (mojibake TOTAL,
                    # container rows/headers, `Export Carrier` + value).
                    rows.append((text, " ".join(t for _, t in spans[1:]), x0))
                    index += 1
                elif len(spans) > 1:
                    rows.append((None, " ".join(t for _, t in spans), x0))
                    index += 1
                elif (
                    x0 < LABEL_COL_X
                    and ":" not in text
                    and nxt is not None
                    and len(nxt[1]) == 1
                    and nxt[1][0][0] >= LABEL_COL_X
                    and abs(nxt[0] - y) <= BASELINE_TOLERANCE
                ):
                    rows.append((text, nxt[1][0][1], x0))
                    index += 2
                elif ":" in text:
                    split = _split_colon(text)
                    if split is None:
                        rows.append((None, text, x0))
                    else:
                        rows.append((split[0], split[1], x0))
                    index += 1
                else:
                    rows.append((None, text, x0))
                    index += 1
            # A value block never continues across a page break.
            rows.append((None, "\x00PAGE-BREAK\x00", -1.0))
        # Phase 2: emit pairs; continuations attach to the last live label.
        pairs: list[tuple[str, str]] = []
        live = False
        for label, value, x0 in rows:
            if label is not None:
                pairs.append((_rewrite_total(label), value))
                # Unknown labels are dropped by parse_text (which resets) and
                # known non-compare labels skip: only compared labels stay
                # live for continuations.
                live = _is_compared(_rewrite_total(label))
            elif value == "\x00PAGE-BREAK\x00":
                live = False
            elif live and x0 >= LABEL_COL_X:
                label_prev, value_prev = pairs.pop()
                pairs.append((label_prev, value_prev + "\n" + value))
            else:
                live = False
    except Exception:
        return unreadable("pdf", "parse failure")
    finally:
        try:
            doc.close()
        except Exception:
            pass
    if text_chars == 0:
        return unreadable("pdf", "no text layer" if has_images else "empty text")
    if not pairs:
        return unreadable("pdf", "no label rows")
    return parse_text(render_pairs(pairs), "pdf")
