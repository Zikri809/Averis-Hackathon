"""Doc-type sniff tests (plan 03 B1).

Sheet titles / headings identify SI vs BL; impostor attachments (501–505)
sniff IMPOSTOR so the router exits ``wrong_doc_type``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
ATTACHMENTS = PROJECT_DIR / "data_v2" / "attachments"

from app.stage2.doctype import (  # noqa: E402
    DOC_BL,
    DOC_IMPOSTOR,
    DOC_SI,
    is_wrong_type,
    sniff,
)


def needs(name: str) -> bytes:
    path = ATTACHMENTS / name
    if not path.is_file():
        pytest.skip("data_v2 attachments not available")
    return path.read_bytes()


def test_xlsx_sheet_titles():
    assert sniff("email_005_SI.xlsx", needs("email_005_SI.xlsx")) == DOC_SI
    assert sniff("email_005_BL.xlsx", needs("email_005_BL.xlsx")) == DOC_BL


def test_docx_headings():
    assert sniff("email_055_BL.docx", needs("email_055_BL.docx")) == DOC_BL


def test_pdf_titles():
    """PDF streams are compressed, so the byte-prefix sniff stays UNKNOWN by
    design — but it must never misfire IMPOSTOR on genuine docs (the router
    proceeds to parse)."""
    assert sniff("email_313_SI.pdf", needs("email_313_SI.pdf")) != DOC_IMPOSTOR
    assert sniff("email_313_BL.pdf", needs("email_313_BL.pdf")) != DOC_IMPOSTOR


def test_impostor_pair_exits_wrong_doc_type():
    """501: genuine SI + COMMERCIAL INVOICE → router exits wrong_doc_type."""
    si_type = sniff("email_501_SI.txt", needs("email_501_SI.txt"))
    bl_type = sniff("email_501_BL.txt", needs("email_501_BL.txt"))
    assert si_type == DOC_SI
    assert bl_type == DOC_IMPOSTOR
    assert is_wrong_type(bl_type, "BL") is True

    import json

    from app.loader_client import LoaderClient
    from app.stage2 import router

    inbox = PROJECT_DIR / "data_v2" / "inbox"
    if not inbox.is_dir():
        pytest.skip("data_v2 not available")
    client = LoaderClient(PROJECT_DIR / "data_v2")
    email = json.loads((inbox / "email_501.json").read_text(encoding="utf-8"))
    result = router.extract_pair(email, client)
    assert result.doc_status == "NEEDS_REVIEW"
    assert result.review_reason == "wrong_doc_type"


def test_wrong_type_gate():
    assert is_wrong_type(DOC_IMPOSTOR, "SI") is True
    assert is_wrong_type(DOC_SI, "BL") is True
    assert is_wrong_type(DOC_SI, "SI") is False
