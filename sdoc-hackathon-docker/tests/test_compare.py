"""Stage-3 comparison truth table."""
from __future__ import annotations

from app.schema import COMPARE_FIELDS, DocRecord, FieldEvidence, ExtractionResult, Verdict
from app.stage3_compare import compare
from app.stage3_normalize import normalize_port


def doc(**overrides):
    fields = {
        "shipper": "ACME EXPORTS LLC",
        "consignee": "BETA IMPORTS SDN BHD",
        "notify_party": "OMEGA LOGISTICS",
        "port_of_loading": "PORT KLANG (WESTPORT), MALAYSIA",
        "port_of_discharge": "MOMBASA, KENYA",
        "container_count": 3,
        "gross_weight_kg": 21577.0,
    }
    fields.update(overrides)
    evidence = {
        field: FieldEvidence(value=value, raw=str(value), label_found=field)
        for field, value in fields.items()
    }
    return DocRecord(fields=fields, evidence=evidence)


def test_clean_pair_has_no_defects_and_report_for_each_field():
    verdict = compare(doc(), doc())
    assert isinstance(verdict, Verdict)
    assert verdict.has_defect is False
    assert verdict.defect_fields == []
    assert set(COMPARE_FIELDS) <= set(verdict.diff_report)
    assert verdict.diff_report["_summary"]["message"] == "No mismatch detected"


def test_all_field_types_can_differ():
    verdict = compare(
        doc(),
        doc(
            shipper="OTHER EXPORTS LLC",
            consignee="GAMMA IMPORTS SDN BHD",
            notify_party="SIGMA LOGISTICS",
            port_of_loading="TUTICORIN, INDIA (INTUT)",
            port_of_discharge="PORT KELANG, MALAYSIA (MYPKG)",
            container_count=4,
            gross_weight_kg=22577.0,
        ),
    )
    assert isinstance(verdict, Verdict)
    assert verdict.defect_fields == COMPARE_FIELDS


def test_punctuation_case_and_whitespace_are_ignored_for_parties():
    verdict = compare(
        doc(shipper="East Bright FZ-LLC"),
        doc(shipper="  east bright fz llc  "),
    )
    assert isinstance(verdict, Verdict)
    assert verdict.defect_fields == []


def test_port_compare_strips_locode_and_qualifier_but_keeps_name():
    assert normalize_port("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)") == "PORT KLANG MALAYSIA"
    verdict = compare(
        doc(port_of_discharge="MOMBASA, KENYA (KEMBA)"),
        doc(port_of_discharge="TUTICORIN, INDIA (KEMBA)"),
    )
    assert isinstance(verdict, Verdict)
    assert verdict.defect_fields == ["port_of_discharge"]


def test_numeric_equality_is_exact_after_comma_strip():
    verdict = compare(doc(gross_weight_kg="243,588"), doc(gross_weight_kg=243588.0))
    assert isinstance(verdict, Verdict)
    assert verdict.defect_fields == []

    verdict = compare(doc(container_count=3), doc(container_count=4))
    assert isinstance(verdict, Verdict)
    assert verdict.defect_fields == ["container_count"]


def test_null_reaching_stage3_escalates_to_missing_value():
    result = compare(doc(consignee=None), doc())
    assert isinstance(result, ExtractionResult)
    assert result.doc_status == "NEEDS_REVIEW"
    assert result.review_reason == "missing_value"


def test_on_behalf_chain_exact_counterpart_escalates_not_defects():
    si = doc(shipper="AGENT LINE")
    bl = doc(shipper="TRUE EXPORTER LTD")
    si.evidence["shipper"].raw = "AGENT LINE | ON BEHALF OF TRUE EXPORTER LTD"

    result = compare(si, bl)

    assert isinstance(result, ExtractionResult)
    assert result.review_reason == "missing_value"


def test_on_behalf_guard_does_not_fire_for_prefix_only():
    si = doc(shipper="APRIL FINE PAPER TRADING")
    bl = doc(shipper="APRIL FINE PAPER TRADING (MIDDLE EAST) FZE")
    bl.evidence["shipper"].raw = (
        "APRIL FINE PAPER TRADING (MIDDLE EAST) FZE | "
        "ON BEHALF OF APRIL FINE PAPER TRADING (MIDDLE EAST) FZE"
    )

    verdict = compare(si, bl)

    assert isinstance(verdict, Verdict)
    assert verdict.defect_fields == ["shipper"]
