"""Value normalizers on real files (plan 02 T4/T5)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.stage2.txt_parser import parse_text

DATA_DIR = Path(__file__).resolve().parent.parent / "data_v2"
ATTACH_DIR = DATA_DIR / "attachments"


def read(name: str) -> str:
    return (ATTACH_DIR / name).read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize(
    "name,expected_count",
    [
        ("email_001_SI.txt", 1),
        ("email_144_SI.txt", 12),
        ("email_516_SI.txt", 10),
        ("email_517_SI.txt", 15),
        ("email_520_SI.txt", 6),
    ],
)
def test_counts_are_ints(name, expected_count):
    doc = parse_text(read(name), "txt")
    assert doc.fields["container_count"] == expected_count
    assert isinstance(doc.fields["container_count"], int)


@pytest.mark.parametrize(
    "name,expected_weight",
    [
        ("email_001_SI.txt", 21577.0),
        ("email_144_SI.txt", 264180.0),
        ("email_519_SI.txt", 70572.0),
        ("email_520_SI.txt", 122640.0),
    ],
)
def test_weights_are_floats_in_kg(name, expected_weight):
    doc = parse_text(read(name), "txt")
    assert doc.fields["gross_weight_kg"] == expected_weight
    assert isinstance(doc.fields["gross_weight_kg"], float)


def test_port_name_and_code_separation():
    doc = parse_text("POL: PORT KLANG (WESTPORT), MALAYSIA (MYPKG)\n", "txt")
    assert doc.fields["port_of_loading"] == "PORT KLANG (WESTPORT), MALAYSIA"


def test_port_without_code_is_still_extracted():
    doc = parse_text("POL: SINGAPORE\n", "txt")
    assert doc.fields["port_of_loading"] == "SINGAPORE"


def test_party_identity_is_first_segment():
    doc = parse_text("Consignee: ACME LTD | 1 ROAD; CITY\n", "txt")
    assert doc.fields["consignee"] == "ACME LTD"
    assert "1 ROAD" in (doc.evidence["consignee"].raw or "")


def test_win32_charmap_safe_read():
    """519_SI contains CJK; reads must never raise (encoding trap)."""
    text = read("email_519_SI.txt")
    doc = parse_text(text, "txt")
    assert doc.readable is True
