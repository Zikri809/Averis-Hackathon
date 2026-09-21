"""Real-file parser snapshots (plan 02 T2/T6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.stage2.txt_parser import LABEL_RX, parse_text, split_party, split_port

DATA_DIR = Path(__file__).resolve().parent.parent / "data_v2"
ATTACH_DIR = DATA_DIR / "attachments"


def read(name: str) -> str:
    return (ATTACH_DIR / name).read_text(encoding="utf-8", errors="replace")


def parse(name: str):
    return parse_text(read(name), "txt")


def test_001_both_sides_extract_identically():
    si = parse("email_001_SI.txt")
    bl = parse("email_001_BL.txt")
    assert si.fields == bl.fields
    assert si.fields["shipper"] == "APRIL FAR EAST (M) SDN BHD"
    assert si.fields["consignee"] == "MOORIM SP CO., LTD"
    assert si.fields["port_of_loading"] == "PORT KLANG (WESTPORT), MALAYSIA"
    assert si.fields["container_count"] == 1
    assert si.fields["gross_weight_kg"] == 21577.0
    assert si.readable is True


def test_144_indented_colon_line_is_a_continuation():
    """The guard that protects the gold consignee defect on 144."""
    si = parse("email_144_SI.txt")
    assert si.fields["consignee"] == "NAGAPPA EXPORTS"
    assert "NEW NO : 23" in (si.evidence["consignee"].raw or "")
    bl = parse("email_144_BL.txt")
    assert bl.fields["consignee"] == "PACIFIC OFFICE (M) SDN BHD"
    assert si.fields["consignee"] != bl.fields["consignee"]
    assert bl.fields["container_count"] == 11
    assert si.fields["container_count"] == 12


def test_144_indented_line_would_be_a_label_without_the_guard():
    """Regression proof: the raw regex would match the address line."""
    line = "  NEW NO : 23, L-BLOCK, 17TH STREET"
    assert LABEL_RX.match(line.strip()) is not None  # why the guard exists


def test_519_cjk_blanks_and_missing_value():
    si = parse("email_519_SI.txt")
    assert si.fields["shipper"] is None
    assert si.fields["container_count"] is None
    assert si.fields["gross_weight_kg"] == 70572.0
    assert si.fields["consignee"] == "UAB NOVAKOPA"


def test_520_blank_consignee_and_chain_in_evidence():
    si = parse("email_520_SI.txt")
    assert si.fields["consignee"] is None
    assert si.fields["notify_party"] == "CLIFFORD PAPER INC"
    bl = parse("email_520_BL.txt")
    assert bl.fields["consignee"] == "CLIFFORD PAPER INC"
    # The identity is the first line; the ON BEHALF OF chain is evidence only
    # (Stage 3's literal-token guard reads it, the value never includes it).
    assert bl.fields["shipper"] == "APRIL FINE PAPER TRADING"
    assert "ON BEHALF OF" in (bl.evidence["shipper"].raw or "")
    assert "70 EAST STREET" in (bl.evidence["consignee"].raw or "")


def test_on_behalf_of_chain_stays_out_of_identity():
    si = parse("email_144_SI.txt")
    assert si.fields["shipper"] == "APRIL FINE PAPER TRADING"
    assert "ON BEHALF OF" in (si.evidence["shipper"].raw or "")


def test_net_weight_is_never_gross_weight():
    for name in ("email_516_SI.txt", "email_517_SI.txt", "email_519_SI.txt", "email_520_SI.txt"):
        doc = parse(name)
        assert "NET WEIGHT" not in (doc.evidence["gross_weight_kg"].label_found or "")


def test_blank_tokens_become_null():
    doc = parse("email_517_SI.txt")
    assert doc.fields["port_of_loading"] is None
    assert doc.fields["port_of_discharge"] is None
    assert doc.fields["gross_weight_kg"] == 340770.0


def test_516_n_a_weight_is_null():
    doc = parse("email_516_SI.txt")
    assert doc.fields["gross_weight_kg"] is None
    assert doc.fields["container_count"] == 10


def test_518_two_blanks():
    doc = parse("email_518_SI.txt")
    assert doc.fields["port_of_discharge"] is None
    assert doc.fields["gross_weight_kg"] is None
    assert doc.fields["port_of_loading"] == "NANTONG, CHINA"


def test_unknown_labels_are_recorded_not_guessed():
    doc = parse_text("Loading Port: MARS\nConsignee: ACME\n", "txt")
    assert doc.fields["port_of_loading"] is None
    assert doc.fields["consignee"] == "ACME"
    assert "Loading Port" in doc.unknown_labels


def test_impostor_invoice_has_no_compared_fields():
    doc = parse("email_501_BL.txt")
    assert doc.fields["consignee"] is None
    assert doc.fields["port_of_loading"] is None


def test_split_party_and_split_port_helpers():
    assert split_party("ACME LTD; 1 ROAD; CITY") == ("ACME LTD", "1 ROAD | CITY")
    assert split_party("") == ("", "")
    assert split_port("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)") == (
        "PORT KLANG (WESTPORT), MALAYSIA",
        "MYPKG",
    )
    assert split_port("NANTONG, CHINA") == ("NANTONG, CHINA", None)


def test_blank_value_with_label_present_is_null_not_missing_label():
    doc = parse_text("SHIPPER: \nCONSIGNEE: ACME\n", "txt")
    assert doc.fields["shipper"] is None
    assert doc.evidence["shipper"].label_found == "SHIPPER"
