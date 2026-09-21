"""``.pdf`` parser tests (plan 03 B4/B5).

Same-baseline span pairing, the TOTAL-line weight anchor (never a container
row), the mojibake prefix rule, and the locodeless-port case.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
ATTACHMENTS = PROJECT_DIR / "data_v2" / "attachments"

pytest.importorskip("pymupdf")

from app.stage2.pdf_parser import parse_pdf  # noqa: E402


def needs_data():
    if not (ATTACHMENTS / "email_313_BL.pdf").is_file():
        pytest.skip("data_v2 attachments not available")


def read(name: str) -> bytes:
    return (ATTACHMENTS / name).read_bytes()


def test_two_field_defect_values():
    """313: BL 4 × 117770 vs SI 5 × 118270 (the v3-A6 worked example)."""
    needs_data()
    bl = parse_pdf("email_313_BL.pdf", read("email_313_BL.pdf"), None)
    si = parse_pdf("email_313_SI.pdf", read("email_313_SI.pdf"), None)
    assert bl.fields["container_count"] == 4
    assert bl.fields["gross_weight_kg"] == 117770.0
    assert si.fields["container_count"] == 5
    assert si.fields["gross_weight_kg"] == 118270.0


def test_weight_comes_from_total_not_container_rows():
    """The header has no value span; container rows must never be the weight."""
    needs_data()
    bl = parse_pdf("email_313_BL.pdf", read("email_313_BL.pdf"), None)
    assert bl.fields["gross_weight_kg"] == 117770.0  # not 29442 / 29444
    assert bl.evidence["gross_weight_kg"].label_found == "Gross Weight"


def test_mojibake_pairs_show_no_false_weight_diff():
    """208/411 OK pairs: joined-span TOTAL weights agree SI == BL."""
    needs_data()
    for email_id in ("email_208", "email_411"):
        si = parse_pdf(f"{email_id}_SI.pdf", read(f"{email_id}_SI.pdf"), None)
        bl = parse_pdf(f"{email_id}_BL.pdf", read(f"{email_id}_BL.pdf"), None)
        assert si.fields["gross_weight_kg"] == bl.fields["gross_weight_kg"]
        assert si.fields["container_count"] == bl.fields["container_count"]


def test_locodeless_port_value_extracted():
    """434: `CEBU, PHILIPPINES` vs `BUSAN, SOUTH KOREA` — no code assumed."""
    needs_data()
    bl = parse_pdf("email_434_BL.pdf", read("email_434_BL.pdf"), None)
    si = parse_pdf("email_434_SI.pdf", read("email_434_SI.pdf"), None)
    assert bl.fields["port_of_discharge"] == "CEBU, PHILIPPINES"
    assert si.fields["port_of_discharge"] == "BUSAN, SOUTH KOREA"


def test_ok_pair_weights_agree_across_label_variants():
    """059: `TOTAL Gross Weight (KG)` vs `TOTAL Gross Wt (kgs)` → 131322."""
    needs_data()
    si = parse_pdf("email_059_SI.pdf", read("email_059_SI.pdf"), None)
    bl = parse_pdf("email_059_BL.pdf", read("email_059_BL.pdf"), None)
    assert si.fields["gross_weight_kg"] == 131322.0 == bl.fields["gross_weight_kg"]


def test_empty_input_is_unreadable():
    needs_data()
    assert parse_pdf("x.pdf", b"", None).readable is False
