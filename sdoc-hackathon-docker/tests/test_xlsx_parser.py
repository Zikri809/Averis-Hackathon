"""``.xlsx`` parser tests (plan 03 B2).

Covers the alias-hit row filter, raw-int weights (v3-A2), the ``" | "``
party split, and the CJK label path — all against real attachments.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
ATTACHMENTS = PROJECT_DIR / "data_v2" / "attachments"

pytest.importorskip("openpyxl")

from app.stage2.xlsx_parser import parse_xlsx  # noqa: E402


def needs_data():
    if not (ATTACHMENTS / "email_005_SI.xlsx").is_file():
        pytest.skip("data_v2 attachments not available")


def read(name: str) -> bytes:
    return (ATTACHMENTS / name).read_bytes()


def test_ok_pair_parses_equal_with_raw_int_weight():
    """005 SI == BL: count 15, weight 341715 (B10-style raw number, no unit)."""
    needs_data()
    si = parse_xlsx("email_005_SI.xlsx", read("email_005_SI.xlsx"), None)
    bl = parse_xlsx("email_005_BL.xlsx", read("email_005_BL.xlsx"), None)
    assert si.readable and bl.readable
    assert si.fields["container_count"] == 15 == bl.fields["container_count"]
    assert si.fields["gross_weight_kg"] == 341715.0 == bl.fields["gross_weight_kg"]
    for field in ("shipper", "consignee", "notify_party", "port_of_loading", "port_of_discharge"):
        assert si.fields[field] == bl.fields[field], field


def test_cjk_label_and_locodeless_port():
    """243_BL: `Gross Weight毛重(KGS)` + `PORT KLANG (WESTPORT)`-style name."""
    needs_data()
    bl = parse_xlsx("email_243_BL.xlsx", read("email_243_BL.xlsx"), None)
    assert bl.fields["gross_weight_kg"] == 100445.0
    assert bl.fields["container_count"] == 5
    assert bl.fields["port_of_loading"] == "RUGAO/NANTONG/SHANGHAI, CHINA"
    assert bl.evidence["gross_weight_kg"].label_found == "Gross Weight毛重(KGS)"


def test_noise_rows_require_no_alias_hit():
    """Title / `BL INSTRUCTION` / booking rows never become compared fields."""
    needs_data()
    si = parse_xlsx("email_005_SI.xlsx", read("email_005_SI.xlsx"), None)
    assert si.fields["shipper"] == "ASIA PACIFIC PAPERBOARD TRADING PTE LTD"
    unknowns = " ".join(getattr(si, "unknown_labels", ()))
    assert "BL INSTRUCTION" in unknowns


def test_party_identity_splits_on_pipe():
    """`NAME | addr1; addr2` → first part is the identity (055/462 OK pairs)."""
    needs_data()
    for name in ("email_055_SI.xlsx", "email_462_SI.xlsx"):
        doc = parse_xlsx(name, read(name), None)
        assert doc.readable
        assert "|" not in str(doc.fields["shipper"])
        assert doc.fields["shipper"]


def test_empty_and_corrupt_inputs_are_unreadable():
    needs_data()
    assert parse_xlsx("x.xlsx", b"", None).readable is False
    assert parse_xlsx("x.xlsx", b"not a zip at all", None).readable is False
