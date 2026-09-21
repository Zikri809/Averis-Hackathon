"""Shared synthesis for the binary parsers (plan 03).

Every binary parser renders its document as ``Label: value`` text lines and
delegates to :func:`app.stage2.txt_parser.parse_text`, so alias lookup (v3-A4),
non-compare skips, duplicate handling, and the typed normalizers (v3-A2) behave
identically across formats. Multi-line values are emitted as an initial
``Label: first-line`` followed by **indented** continuation lines — the same
convention the ``.txt`` sources use — so address chains and ``ON BEHALF OF``
blocks stay in evidence and colon-bearing lines inside them (``TEL:…``,
``P.O. BOX:…``, ``NEW NO :…``) are never parsed as labels.
"""
from __future__ import annotations

from ..schema import COMPARE_FIELDS, DocRecord, FieldEvidence


def render_pairs(pairs: list[tuple[str, str | None]]) -> str:
    """Render ``(label, value)`` pairs as ``parse_text``-ready text.

    Blank values emit a bare ``Label:`` line (records the label so a missing
    value exits ``missing_value`` instead of vanishing). Blank continuation
    lines are dropped.
    """
    lines: list[str] = []
    for label, value in pairs:
        label_text = str(label).strip()
        if not label_text:
            continue
        parts = str(value or "").splitlines() or [""]
        first = parts[0].strip()
        lines.append(f"{label_text}: {first}".rstrip())
        for rest in parts[1:]:
            rest_text = rest.strip()
            if rest_text:
                lines.append(f" {rest_text}")
    return "\n".join(lines)


def unreadable(source_format: str, note: str = "unsupported format") -> DocRecord:
    """A ``readable: False`` document; the router exits ``NEEDS_REVIEW/unreadable``."""
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
    return DocRecord(
        fields=fields, readable=False, source_format=source_format, evidence=evidence
    )
