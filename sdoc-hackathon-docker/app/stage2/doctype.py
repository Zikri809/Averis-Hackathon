"""Shared document-type sniffing for Stage 2.

The router calls this before extraction so invoice / packing-list /
certificate attachments do not degrade into ordinary ``missing_value``
outcomes. Binary parsers can reuse the same API in W3; the implementation here
keeps dependencies to the stdlib so the W2 text route is not blocked.
"""
from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

DOC_SI = "SI"
DOC_BL = "BL"
DOC_IMPOSTOR = "IMPOSTOR"
DOC_UNKNOWN = "UNKNOWN"

_WS = re.compile(r"\s+")
_XML_TAG = re.compile(r"<[^>]+>")

_SI_RX = re.compile(r"\b(SHIPPING\s+INSTRUCTION|S\.?\s*I\.?)\b", re.IGNORECASE)
_BL_RX = re.compile(r"\b(BILL\s+OF\s+LADING|B/L|BL(?:\s+DRAFT)?)\b", re.IGNORECASE)
_IMPOSTOR_RX = re.compile(
    r"\b(COMMERCIAL\s+INVOICE|PACKING\s+LIST|CERTIFICATE\s+OF\s+ORIGIN)\b",
    re.IGNORECASE,
)


def sniff(path: str | Path, data: bytes) -> str:
    """Return ``SI``, ``BL``, ``IMPOSTOR`` or ``UNKNOWN`` for an attachment."""
    suffix = Path(str(path)).suffix.lower()
    if suffix == ".txt":
        return sniff_text(data.decode("utf-8", errors="replace"))
    if suffix in {".xlsx", ".docx"}:
        return sniff_zip_office(data, suffix)
    if suffix == ".pdf":
        # A lightweight pre-parser sniff. The real PDF text-layer parser owns
        # robust extraction; this catches obvious headings when present.
        return sniff_text(data[:4096].decode("latin-1", errors="ignore"))
    return DOC_UNKNOWN


def sniff_bytes(path: str | Path, data: bytes) -> str:
    """Compatibility wrapper for callers that prefer explicit byte naming."""
    return sniff(path, data)


def sniff_doc_type(path: str | Path, data: bytes) -> str:
    """Compatibility wrapper for tests / binary parsers."""
    return sniff(path, data)


def sniff_text(text: str) -> str:
    """Sniff from the first non-empty text line, falling back to a short prefix."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    first = lines[0] if lines else ""
    candidate = _normalize_text(" ".join([first, " ".join(lines[:3])]))
    return _classify(candidate)


def sniff_zip_office(data: bytes, suffix: str) -> str:
    """Best-effort sniff for xlsx sheet titles and docx text without dependencies."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            if suffix == ".xlsx":
                text = _xlsx_titles(archive)
            else:
                text = _docx_text_prefix(archive)
    except Exception:
        return DOC_UNKNOWN
    return sniff_text(text)


def is_wrong_type(found: str, expected_role: str | None) -> bool:
    """True when a sniffed type should short-circuit to ``wrong_doc_type``."""
    if found == DOC_IMPOSTOR:
        return True
    if expected_role in {DOC_SI, DOC_BL} and found in {DOC_SI, DOC_BL}:
        return found != expected_role
    return False


def _classify(text: str) -> str:
    if not text:
        return DOC_UNKNOWN
    if _IMPOSTOR_RX.search(text):
        return DOC_IMPOSTOR
    if _SI_RX.search(text):
        return DOC_SI
    if _BL_RX.search(text):
        return DOC_BL
    return DOC_UNKNOWN


def _normalize_text(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _xlsx_titles(archive: zipfile.ZipFile) -> str:
    workbook = archive.read("xl/workbook.xml")
    root = ElementTree.fromstring(workbook)
    titles: list[str] = []
    for elem in root.iter():
        title = elem.attrib.get("name")
        if title:
            titles.append(title)
    return "\n".join(titles)


def _docx_text_prefix(archive: zipfile.ZipFile) -> str:
    xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    text = _XML_TAG.sub(" ", xml)
    return _normalize_text(text[:2000])
