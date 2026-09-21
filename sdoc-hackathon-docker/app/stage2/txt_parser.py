"""Plain-text SI/BL parser (plan 02 T2/T4/T5/T6).

Parsing order is part of the contract:

1. **Leading-whitespace guard first** — an indented line is a continuation of
   the previous value, never a label. Without this, ``email_144``'s
   ``  NEW NO : 23, L-BLOCK…`` address line would be parsed as a label and
   corrupt the consignee on a gold-defect email.
2. Label regex ``^([^:]{2,40}):\\s*(.*)$``.
3. Alias lookup — exact match on the normalized label (v3-A4). Unknown labels
   are recorded as evidence and ignored; ``NET WEIGHT`` is explicitly ignored
   (it is not ``gross_weight_kg``).
4. Continuation lines append to the previous value.

Values are normalized by the Foundation helpers: parties keep the first line
as identity (the ``ON BEHALF OF`` chain stays in evidence), ports split name
from code, counts and weights become typed.
"""
from __future__ import annotations

import re

from ..normalize import is_blank, parse_count, parse_weight
from ..schema import COMPARE_FIELDS, DocRecord, FieldEvidence
from .aliases import canonical, is_known_non_compare

#: A label is 2–40 chars, no colon, then ``:`` and the value.
LABEL_RX = re.compile(r"^([^:]{2,40}):\s*(.*)$")

#: A trailing UN/LOCODE-ish code, e.g. ``(MYPKG)``.
LOCODE_RX = re.compile(r"\(([A-Z]{5})\)\s*$")


def _new_fields() -> dict:
    return {field_name: None for field_name in COMPARE_FIELDS}


def split_port(value: str) -> tuple[str, str | None]:
    """Split ``"PORT KLANG (WESTPORT), MALAYSIA (MYPKG)"`` into name and code.

    The name keeps its qualifier (Stage 3 strips it for comparison only) and
    the code is ``None`` when absent.
    """
    text = (value or "").strip()
    code: str | None = None
    match = LOCODE_RX.search(text)
    if match:
        code = match.group(1)
        text = text[: match.start()].strip()
    return text.rstrip(", ").strip(), code


def split_party(value: str) -> tuple[str, str]:
    """Split a party value into ``(identity, chain)``.

    The identity is the first non-empty line/segment; the remainder (address,
    ``ON BEHALF OF`` chain) is kept verbatim for evidence.
    """
    text = (value or "").strip()
    if not text:
        return "", ""
    # ``; `` is the txt separator, ``\n`` the docx one, `` | `` the xlsx one.
    lines = [line.strip() for line in re.split(r"\s*[;|]\s*|\n", text) if line.strip()]
    identity = lines[0] if lines else ""
    chain = " | ".join(lines[1:]) if len(lines) > 1 else ""
    return identity, chain


def parse_text(text: str, source_format: str = "txt") -> DocRecord:
    """Parse SI/BL text into a :class:`DocRecord`."""
    fields = _new_fields()
    evidence: dict[str, FieldEvidence] = {}
    raw_labels: dict[str, str] = {}
    values: dict[str, str] = {}
    continuations: dict[str, list[str]] = {}
    duplicate_values: dict[str, list[str]] = {}
    pending_field: str | None = None
    unknown_labels: list[str] = []

    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        # 1. leading whitespace => continuation (address / chain), never a
        #    label and never part of the identity (plan 02 T2/T6).
        if line[:1].isspace():
            if pending_field is not None:
                continuations.setdefault(pending_field, []).append(line.strip())
            continue

        match = LABEL_RX.match(line)
        if match is None:
            continue
        raw_label, raw_value = match.group(1).strip(), match.group(2).strip()

        if is_known_non_compare(raw_label) is not None:
            pending_field = None
            continue

        field_name = canonical(raw_label)
        if field_name is None:
            unknown_labels.append(raw_label)
            pending_field = None
            continue

        raw_labels[field_name] = raw_label
        if field_name in values and not is_blank(values[field_name]):
            # Two lines for the same field: keep the first non-blank and note
            # the conflict in evidence (display-only confidence 0.5).
            duplicate_values.setdefault(field_name, []).append(raw_value)
            pending_field = field_name
            continue

        values[field_name] = raw_value
        pending_field = field_name

    for field_name in COMPARE_FIELDS:
        raw_label = raw_labels.get(field_name)
        if raw_label is None:
            continue
        raw_value = values.get(field_name, "")

        value: object
        chain = " | ".join(continuations.get(field_name, []))
        if field_name in ("shipper", "consignee", "notify_party"):
            identity, inline_chain = split_party(raw_value)
            chain = " | ".join(part for part in (inline_chain, chain) if part)
            value = None if is_blank(identity) else identity
        elif field_name in ("port_of_loading", "port_of_discharge"):
            name, _code = split_port(raw_value)
            value = None if is_blank(name) else name
        elif field_name == "container_count":
            value = parse_count(raw_value)
        else:  # gross_weight_kg
            value = parse_weight(raw_value, source_format)

        fields[field_name] = value
        raw_parts = [part for part in (raw_value, chain, *duplicate_values.get(field_name, [])) if part]
        evidence[field_name] = FieldEvidence(
            value=value,
            raw=" | ".join(raw_parts) or None,
            label_found=raw_label,
            source_format=source_format,
            confidence=0.5 if field_name in duplicate_values else 1.0,
        )

    doc = DocRecord(fields=fields, readable=True, source_format=source_format, evidence=evidence)
    doc.unknown_labels = tuple(unknown_labels)  # type: ignore[attr-defined]
    return doc


def missing_fields(doc: DocRecord) -> list[str]:
    """Compared fields that are blank after normalization."""
    return [field_name for field_name in COMPARE_FIELDS if doc.fields.get(field_name) is None]


def has_missing_value(doc: DocRecord) -> bool:
    return bool(missing_fields(doc))
