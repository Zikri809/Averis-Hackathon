"""``.docx`` parser tests (plan 03 B3).

Bilingual label suffixes, first-line party identity with ``ON BEHALF OF``
chains, and comma weights without units (v3-A2).
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
ATTACHMENTS = PROJECT_DIR / "data_v2" / "attachments"

pytest.importorskip("docx")

from app.stage2.docx_parser import parse_docx  # noqa: E402


def needs_data():
    if not (ATTACHMENTS / "email_055_BL.docx").is_file():
        pytest.skip("data_v2 attachments not available")


def read(name: str) -> bytes:
    return (ATTACHMENTS / name).read_bytes()


def test_ok_pair_weight_and_identity():
    """055_BL: `243,588` → 243588.0; shipper identity is the first line."""
    needs_data()
    bl = parse_docx("email_055_BL.docx", read("email_055_BL.docx"), None)
    assert bl.readable
    assert bl.fields["gross_weight_kg"] == 243588.0
    assert bl.fields["container_count"] == 12
    assert bl.fields["shipper"] == "APRIL FINE PAPER TRADING"
    assert "ON BEHALF OF" in str(bl.evidence["shipper"].raw)


def test_bilingual_labels_resolve():
    """`Notify (通知人)` → notify_party; `POD (卸货港)` → port_of_discharge."""
    needs_data()
    bl = parse_docx("email_055_BL.docx", read("email_055_BL.docx"), None)
    assert bl.fields["notify_party"] == "AL GURG STATIONERY LLC"
    assert bl.fields["port_of_discharge"] == "KARACHI, PAKISTAN"
    assert bl.evidence["notify_party"].label_found == "Notify (通知人)"


def test_cjk_mixed_weight_label():
    """107_BL: `Gross Weight毛重(KGS) (毛重 KGS)` → 41124.0."""
    needs_data()
    bl = parse_docx("email_107_BL.docx", read("email_107_BL.docx"), None)
    assert bl.fields["gross_weight_kg"] == 41124.0
    assert bl.fields["container_count"] == 3


def test_long_bilingual_label_fits_lookup():
    """097_BL: 41-char `Notify Party/Intermediate Consignee (通知人)` parses."""
    needs_data()
    bl = parse_docx("email_097_BL.docx", read("email_097_BL.docx"), None)
    assert bl.fields["notify_party"] == "NAGAPPA EXPORTS"
    assert bl.fields["gross_weight_kg"] == 215950.0
    assert bl.fields["container_count"] == 11


def test_empty_and_corrupt_inputs_are_unreadable():
    needs_data()
    assert parse_docx("x.docx", b"", None).readable is False
    assert parse_docx("x.docx", b"not a zip at all", None).readable is False
