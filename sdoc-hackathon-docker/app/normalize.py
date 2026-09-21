"""String / value normalization (plan 00, F2).

This module owns the three v3 corrections that every stage depends on:

* **v3-A3** — :func:`norm_label` strips **all non-ASCII** before punctuation
  collapse, so the generator label ``Gross Weight毛重(KGS)`` normalizes to
  ``GROSS WEIGHT`` (the raw label is kept in evidence by the caller).
* **v3-A4** — :func:`canonical` matches the **whole** normalized label against
  the alias table, iterating aliases longest-first as a tiebreak only.
  Substring/containment matching is forbidden: it is the only way
  ``Notify Party/Intermediate Consignee`` could be routed into ``consignee``.
* **v3-A2** — :func:`parse_weight` requires a ``KG``/``KGS`` marker for
  text formats only; binary cell-typed values (``.xlsx``/``.docx``) are
  accepted as KG without a unit token. A unit is never guessed from a string.

Only stdlib; no I/O, no imports from other app modules.
"""
from __future__ import annotations

import hashlib
import re

#: Formats whose values are typed by the parser (v3-A2) rather than by text.
BINARY_FORMATS = ("xlsx", "docx")

_NON_ASCII = re.compile(r"[^\x00-\x7F]")
_PARENS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_PUNCT = re.compile(r"[^A-Z0-9]+")
_WS = re.compile(r"\s+")
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
_PURE_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
_LEADING_INT = re.compile(r"^(\d+)")
_UNIT = re.compile(r"\b(KGS?|KILOS?|KILOGRAMS?)\b", re.IGNORECASE)

#: Tokens that mean "no value", never a comparison value.
BLANK_TOKENS = frozenset(
    {
        "N/A",
        "NA",
        "N.A.",
        "TBA",
        "T.B.A.",
        "TBC",
        "T.B.C.",
        "TBD",
        "???",
        "?",
        "-",
        "--",
        "---",
        "NIL",
        "NONE",
        "NULL",
        "XXX",
        "XXXX",
        "____MT",
        "___MT",
        "MT",
        "MTS",
    }
)

_BLANK_CHARS = frozenset("_?. -/\t\r\n")


def norm_label(label: object) -> str:
    """Normalize a raw document label for alias lookup (v3-A3).

    ASCII-strip -> uppercase -> strip parentheticals (incl. CJK) -> strip
    punctuation -> collapse whitespace. Returns ``""`` for ``None``.
    """
    if label is None:
        return ""
    text = _NON_ASCII.sub("", str(label))
    text = text.upper()
    text = _PARENS.sub(" ", text)
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def norm_compare(value: object) -> str:
    """Normalize a comparison value: uppercase -> strip punctuation -> collapse ws.

    Used for party identity equality (plan 04). Non-ASCII is preserved so that
    a genuine CJK difference is still visible; the generator data is ASCII.
    """
    if value is None:
        return ""
    text = str(value).upper()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def is_blank(value: object) -> bool:
    """True when ``value`` carries no usable content (``N/A``, ``TBA``, ``???``…)."""
    if value is None:
        return True
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return False
    text = str(value).strip()
    if not text:
        return True
    if text.upper() in BLANK_TOKENS:
        return True
    if all(ch in _BLANK_CHARS for ch in text):
        return True
    # "_ _ _ M T", "____MT", "______" variants
    collapsed = re.sub(r"[\s_]+", "", text)
    if collapsed.upper() in {"MT", "MTS"}:
        return True
    return False


def parse_weight(value: object, source_format: str = "txt") -> float | None:
    """Parse a gross weight in KG, or ``None`` when the value is not a weight.

    * Numeric values (openpyxl cells) are accepted as KG (v3-A2).
    * ``.xlsx``/``.docx`` strings that are *pure numbers* are accepted as KG
      (``.docx`` renders ``f"{weight:,}"`` with no unit by construction).
    * ``.txt``/``.pdf``/OCR strings require an explicit ``KG``/``KGS`` marker.
    * Blanks and non-numeric text return ``None`` — a unit is never guessed.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if is_blank(text):
        return None

    cleaned = text.replace(",", "").replace("\u00a0", " ")
    match = _NUMBER.search(cleaned)
    if match is None:
        return None

    if _UNIT.search(cleaned):
        return float(match.group())

    if source_format in BINARY_FORMATS and _PURE_NUMBER.fullmatch(cleaned.strip()):
        return float(match.group())

    return None


def parse_count(value: object) -> int | None:
    """Parse a container count: ``1 x 40'HC`` -> ``1``, bare ints accepted."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip()
    if is_blank(text):
        return None

    match = _LEADING_INT.match(text.replace(",", ""))
    if match is None:
        return None
    return int(match.group(1))


def canonical(label: object, aliases: dict[str, str]) -> str | None:
    """Exact-match a normalized label against ``{normalized_alias: field}`` (v3-A4).

    Iterates aliases longest-first as a tiebreak only. Never substring-matches:
    ``Notify Party/Intermediate Consignee`` must resolve to ``notify_party``,
    never to ``consignee``.
    """
    normalized = norm_label(label)
    if not normalized:
        return None
    if normalized in aliases:
        return aliases[normalized]
    # Defensive: tolerate an un-normalized table; longest-first is a tiebreak.
    for alias, field_name in sorted(aliases.items(), key=lambda kv: len(kv[0]), reverse=True):
        if norm_label(alias) == normalized:
            return field_name
    return None


def compute_alias_table_hash(aliases: dict[str, str]) -> str:
    """Deterministic sha256 of an alias table (enters the checkpoint key)."""
    payload = "\n".join(f"{key}\t{value}" for key, value in sorted(aliases.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def empty_hash() -> str:
    """The canonical hash of "no data" (``sha256(b"")``)."""
    return hashlib.sha256(b"").hexdigest()
