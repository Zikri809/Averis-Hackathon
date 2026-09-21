"""Router contract: registration, role detection, per-file isolation (plan 02 T3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schema import COMPARE_FIELDS
from app.stage2 import router
from app.stage2.txt_parser import parse_text

DATA_DIR = Path(__file__).resolve().parent.parent / "data_v2"


@pytest.fixture(autouse=True)
def clean_registry():
    """Restore the module-level registry after each test."""
    original = dict(router._PARSERS)
    yield
    router._PARSERS.clear()
    router._PARSERS.update(original)


@pytest.fixture()
def txt_registered():
    router.register(".txt", lambda _p, d, _c: parse_text(d.decode("utf-8", errors="replace"), "txt"))
    return router


class FakeClient:
    def __init__(self, blobs: dict[str, bytes]):
        self.blobs = blobs

    def read_bytes(self, path: str) -> bytes:
        return self.blobs[path]


def test_register_normalizes_extension(txt_registered):
    assert ".txt" in router.registered_extensions()
    router.register("csv", lambda *_a: None)
    assert ".csv" in router.registered_extensions()


def test_attachment_role_from_filename():
    assert router.attachment_role("attachments/email_001_SI.txt") == "SI"
    assert router.attachment_role("attachments/email_001_BL.xlsx") == "BL"
    assert router.attachment_role("attachments/other.txt") is None


def test_binary_formats_stub_to_unreadable():
    """W2 stub: unregistered extensions exit unreadable, never crash."""
    client = FakeClient({"a.xlsx": b"PK\x03\x04", "a.pdf": b"%PDF-1.4"})
    for path in ("a.xlsx", "a.pdf"):
        doc = router.parse_attachment(path, client.blobs[path], client)
        assert doc.readable is False
        assert set(doc.fields) == set(COMPARE_FIELDS)
        assert all(value is None for value in doc.fields.values())


def test_empty_file_is_unreadable():
    client = FakeClient({"a.txt": b""})
    doc = router.parse_attachment("a.txt", b"", client)
    assert doc.readable is False


def test_parser_exception_is_isolated():
    def boom(*_args, **_kwargs):
        raise RuntimeError("parser exploded")

    router.register(".txt", boom)
    client = FakeClient({"a.txt": b"x"})
    doc = router.parse_attachment("a.txt", b"x", client)
    assert doc.readable is False
    assert "parse failure" in (doc.evidence["shipper"].raw or "")


def test_read_failure_is_isolated():
    class Broken:
        def read_bytes(self, _path):
            raise OSError("disk gone")

    doc = router._read_and_parse("a.txt", Broken())
    assert doc.readable is False


def test_extract_pair_requires_two_roles():
    result = router.extract_pair({"attachments": []}, FakeClient({}))
    assert result.review_reason == "missing_attachment"


def test_extract_pair_parses_real_files(txt_registered):
    from app.loader_client import LoaderClient

    client = LoaderClient(DATA_DIR)
    email = json.loads((DATA_DIR / "inbox" / "email_001.json").read_text(encoding="utf-8"))
    result = router.extract_pair(email, client)
    assert result.doc_status == "READY"
    assert result.si_doc.fields["gross_weight_kg"] == 21577.0
    assert result.bl_doc.fields["gross_weight_kg"] == 21577.0


def test_extract_pair_reports_missing_value(txt_registered):
    from app.loader_client import LoaderClient

    client = LoaderClient(DATA_DIR)
    email = json.loads((DATA_DIR / "inbox" / "email_520.json").read_text(encoding="utf-8"))
    result = router.extract_pair(email, client)
    assert result.doc_status == "NEEDS_REVIEW"
    assert result.review_reason == "missing_value"


def test_unreadable_when_one_side_fails(txt_registered):
    client = FakeClient(
        {
            "a_SI.txt": b"Consignee: ACME\n",
            "a_BL.pdf": b"%PDF-1.4",
        }
    )
    result = router.extract_pair({"attachments": ["a_SI.txt", "a_BL.pdf"]}, client)
    assert result.doc_status == "NEEDS_REVIEW"
    assert result.review_reason == "unreadable"
