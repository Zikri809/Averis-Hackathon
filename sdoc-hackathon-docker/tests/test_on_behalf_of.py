from __future__ import annotations

from app.schema import DocRecord, FieldEvidence
from app.stage3_compare import compare


def make_doc(shipper: str) -> DocRecord:
    fields = {
        "shipper": shipper,
        "consignee": "C",
        "notify_party": "C",
        "port_of_loading": "SINGAPORE",
        "port_of_discharge": "BUSAN",
        "container_count": 1,
        "gross_weight_kg": 100.0,
    }
    return DocRecord(
        fields=fields,
        evidence={
            field_name: FieldEvidence(value=value, raw=str(value), label_found=field_name)
            for field_name, value in fields.items()
        },
    )


def test_literal_on_behalf_token_required():
    si = make_doc("ACME")
    bl = make_doc("VITAL")
    si.evidence["shipper"].raw = "ACME | O/B VITAL"

    verdict = compare(si, bl)

    assert verdict.defect_fields == ["shipper"]
    assert verdict.review_reason is None


def test_counterpart_must_be_in_on_behalf_segment_not_identity_prefix():
    si = make_doc("APRIL FINE PAPER TRADING")
    bl = make_doc("APRIL FINE PAPER TRADING (MIDDLE EAST) FZE")
    bl.evidence["shipper"].raw = (
        "APRIL FINE PAPER TRADING (MIDDLE EAST) FZE | "
        "ON BEHALF OF VITAL SOLUTIONS PTE LTD"
    )

    verdict = compare(si, bl)

    assert verdict.defect_fields == ["shipper"]
    assert verdict.review_reason is None
