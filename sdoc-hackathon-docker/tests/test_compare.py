from __future__ import annotations

from app.schema import COMPARE_FIELDS, DocRecord, FieldEvidence
from app.stage3_compare import compare
from app.stage3_normalize import port_name


def doc(**overrides):
    fields = {
        "shipper": "APRIL FINE PAPER TRADING",
        "consignee": "PACIFIC OFFICE (M) SDN BHD",
        "notify_party": "PACIFIC OFFICE (M) SDN BHD",
        "port_of_loading": "NANTONG, CHINA",
        "port_of_discharge": "BUSAN, SOUTH KOREA",
        "container_count": 15,
        "gross_weight_kg": 313380.0,
    }
    fields.update(overrides)
    evidence = {
        field_name: FieldEvidence(value=value, raw=None, label_found=field_name)
        for field_name, value in fields.items()
    }
    return DocRecord(fields=fields, evidence=evidence)


def test_all_equal_returns_ok_with_full_report():
    verdict = compare(doc(), doc())
    assert not verdict.has_defect
    assert verdict.defect_fields == []
    assert verdict.review_reason is None
    assert set(verdict.diff_report) == set(COMPARE_FIELDS)


def test_party_punctuation_and_case_are_equal():
    verdict = compare(doc(shipper="A.B, C"), doc(shipper="a b c"))
    assert verdict.defect_fields == []


def test_party_prefix_mutation_is_a_defect_even_with_unrelated_on_behalf_chain():
    si = doc(shipper="APRIL FINE PAPER TRADING")
    bl = doc(shipper="APRIL FINE PAPER TRADING (MIDDLE EAST) FZE")
    si.evidence["shipper"].raw = (
        "APRIL FINE PAPER TRADING | ON BEHALF OF VITAL SOLUTIONS PTE LTD"
    )
    bl.evidence["shipper"].raw = (
        "APRIL FINE PAPER TRADING (MIDDLE EAST) FZE | "
        "ON BEHALF OF VITAL SOLUTIONS PTE LTD"
    )

    verdict = compare(si, bl)

    assert verdict.defect_fields == ["shipper"]
    assert verdict.review_reason is None


def test_on_behalf_of_chain_escalates_mismatched_party():
    si = doc(shipper="ACME TRADING")
    bl = doc(shipper="VITAL SOLUTIONS PTE LTD")
    si.evidence["shipper"].raw = "ACME TRADING | ON BEHALF OF VITAL SOLUTIONS PTE LTD"

    verdict = compare(si, bl)

    assert verdict.review_reason == "missing_value"
    assert verdict.defect_fields == []
    assert verdict.diff_report["shipper"]["outcome"] == "on_behalf_of_review"


def test_ports_compare_name_only_and_strip_qualifiers():
    assert port_name("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)") == port_name(
        "PORT KLANG, MALAYSIA (ABCDE)"
    )
    verdict = compare(
        doc(port_of_discharge="PORT KLANG (WESTPORT), MALAYSIA (MYPKG)"),
        doc(port_of_discharge="PORT KLANG, MALAYSIA (ABCDE)"),
    )
    assert verdict.defect_fields == []


def test_port_name_difference_flags_even_when_code_matches():
    verdict = compare(
        doc(port_of_discharge="SINGAPORE (ABCDE)"),
        doc(port_of_discharge="BUSAN (ABCDE)"),
    )
    assert verdict.defect_fields == ["port_of_discharge"]


def test_counts_and_weights_are_exact_typed_values():
    verdict = compare(doc(container_count=15, gross_weight_kg=243588.0), doc())
    assert verdict.defect_fields == ["gross_weight_kg"]

    verdict = compare(doc(container_count=14), doc())
    assert verdict.defect_fields == ["container_count"]


def test_any_missing_value_escalates_without_defect_fields():
    verdict = compare(doc(consignee=None), doc())
    assert verdict.review_reason == "missing_value"
    assert verdict.defect_fields == []
    assert verdict.diff_report["consignee"]["outcome"] == "missing_value"
