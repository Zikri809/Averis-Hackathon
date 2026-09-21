"""Binary failure paths (plan 03 B6) + router integration.

Corrupt, image-only, empty, and unknown-extension inputs exit
``NEEDS_REVIEW/unreadable`` without crashing the run; the sibling document in
a mixed pair is unaffected.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
ATTACHMENTS = PROJECT_DIR / "data_v2" / "attachments"
INBOX = PROJECT_DIR / "data_v2" / "inbox"


def needs_data():
    if not INBOX.is_dir():
        pytest.skip("data_v2 not available")


def read_attachment(name: str) -> bytes:
    return (ATTACHMENTS / name).read_bytes()


def test_corrupt_pdfs_are_unreadable_but_siblings_parse():
    """511_BL / 515_BL raise in fitz; the .txt SI sides still parse."""
    needs_data()
    from app.stage2 import router
    from app.stage2.binary_parsers import register_all

    register_all(router)

    class Client:
        def read_bytes(self, path):
            return (ATTACHMENTS / Path(path).name).read_bytes()

    client = Client()
    for bl_name in ("email_511_BL.pdf", "email_515_BL.pdf"):
        bl = router.parse_attachment(bl_name, read_attachment(bl_name), client)
        assert bl.readable is False
    si = router.parse_attachment(
        "email_511_SI.txt", read_attachment("email_511_SI.txt"), client
    )
    assert si.readable is True


def test_image_only_pdfs_are_unreadable():
    """512–514: no text layer, embedded image → unreadable (E5, no OCR)."""
    needs_data()
    from app.stage2 import router
    from app.stage2.binary_parsers import register_all

    register_all(router)

    class Client:
        def read_bytes(self, path):
            return (ATTACHMENTS / Path(path).name).read_bytes()

    client = Client()
    for name in (
        "email_512_SI.pdf",
        "email_512_BL.pdf",
        "email_513_SI.pdf",
        "email_513_BL.pdf",
        "email_514_SI.pdf",
        "email_514_BL.pdf",
    ):
        assert router.parse_attachment(name, read_attachment(name), client).readable is False


def test_extract_pair_exits_unreadable_for_mixed_corrupt_pair():
    """email_511 (txt + corrupt pdf) → NEEDS_REVIEW/unreadable via the router."""
    needs_data()
    from app.loader_client import LoaderClient
    from app.stage2 import router
    from app.stage2.binary_parsers import register_all

    register_all(router)
    client = LoaderClient(PROJECT_DIR / "data_v2")
    email = json.loads((INBOX / "email_511.json").read_text(encoding="utf-8"))
    result = router.extract_pair(email, client)
    assert result.doc_status == "NEEDS_REVIEW"
    assert result.review_reason == "unreadable"


def test_extract_pair_is_ready_for_binary_ok_pair():
    """email_005 (xlsx + xlsx OK pair) → READY with complete docs."""
    needs_data()
    from app.loader_client import LoaderClient
    from app.stage2 import router
    from app.stage2.binary_parsers import register_all
    from app.stage2.txt_parser import missing_fields

    register_all(router)
    client = LoaderClient(PROJECT_DIR / "data_v2")
    email = json.loads((INBOX / "email_005.json").read_text(encoding="utf-8"))
    result = router.extract_pair(email, client)
    assert result.doc_status == "READY"
    assert not missing_fields(result.si_doc)
    assert not missing_fields(result.bl_doc)


def test_zero_byte_and_unknown_extension():
    """Synthetic empty file and unknown suffix → unreadable, never raises."""
    needs_data()
    from app.stage2 import router
    from app.stage2.binary_parsers import register_all

    register_all(router)

    class Client:
        def read_bytes(self, path):
            raise FileNotFoundError(path)

    client = Client()
    assert router.parse_attachment("x.xlsx", b"", client).readable is False
    assert router.parse_attachment("x.docx", b"", client).readable is False
    assert router.parse_attachment("x.pdf", b"", client).readable is False
    note = router.parse_attachment("x.zzz", b"data", client)
    assert note.readable is False


def test_register_all_wires_the_three_formats():
    from app.stage2 import router
    from app.stage2.binary_parsers import register_all

    assert register_all(router) == (".xlsx", ".docx", ".pdf")
    assert set((".xlsx", ".docx", ".pdf")) <= set(router.registered_extensions())
