"""Oracle correctness on synthetic fixtures (plan 06 §4).

The verifiers are tested against hand-built submissions so a passing oracle
means the *oracle* is right, not that the pipeline happens to agree with it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.schema import default_submission_record  # noqa: E402
from tools import verify_edges  # noqa: E402

DATA_DIR = PROJECT_DIR / "data_v2"


@pytest.fixture(scope="module")
def dataset():
    client_emails = {}
    for path in sorted((DATA_DIR / "inbox").glob("email_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        client_emails[record["email_id"]] = record
    truth = json.loads((DATA_DIR / "ground_truth.json").read_text(encoding="utf-8"))
    return client_emails, truth


def golden_submission(truth: dict, emails: dict) -> dict:
    """Build the perfect submission from ground truth (the oracle's own target)."""
    submission = {}
    for email_id, record in truth.items():
        if record["status"] == "NEEDS_REVIEW":
            submission[email_id] = {
                "category": "BL_COMPARISON",
                "status": "NEEDS_REVIEW",
                "review_reason": record["review_reason"],
                "defect_fields": [],
                "has_defect": False,
            }
        elif record["has_defect"]:
            submission[email_id] = {
                "category": record["category"],
                "status": "MISMATCH",
                "review_reason": None,
                "defect_fields": list(record["defect_fields"]),
                "has_defect": True,
            }
        else:
            submission[email_id] = default_submission_record(category=record["category"])
    return submission


def test_golden_submission_passes_every_edge_check(dataset):
    emails, truth = dataset
    submission = golden_submission(truth, emails)
    assert verify_edges.check_edges(submission, truth) == []
    assert verify_edges.check_zero_attachment_bls(submission, truth, emails) == []
    assert verify_edges.check_phrase_negatives(submission, truth, emails) == []
    assert verify_edges.check_defects(submission, "all") == []


def test_edge_checker_catches_a_wrong_reason(dataset):
    emails, truth = dataset
    submission = golden_submission(truth, emails)
    submission["email_511"]["review_reason"] = "missing_value"
    failures = verify_edges.check_edges(submission, truth)
    assert any("email_511" in failure for failure in failures)


def test_edge_checker_catches_a_wrong_edge_reason(dataset):
    """The checker only grades the 20 golden edges — a wrong reason must fail."""
    emails, truth = dataset
    submission = golden_submission(truth, emails)
    submission["email_501"] = {
        "category": "BL_COMPARISON",
        "status": "NEEDS_REVIEW",
        "review_reason": "unreadable",
        "defect_fields": [],
        "has_defect": False,
    }
    failures = verify_edges.check_edges(submission, truth)
    assert any("email_501" in failure for failure in failures)


def test_edge_checker_catches_a_non_bl_edge_category(dataset):
    emails, truth = dataset
    submission = golden_submission(truth, emails)
    submission["email_517"] = default_submission_record(category="GENERAL")
    failures = verify_edges.check_edges(submission, truth)
    assert any("email_517" in failure for failure in failures)


def test_phrase_negatives_checker_catches_an_escalated_invoice(dataset):
    emails, truth = dataset
    submission = golden_submission(truth, emails)
    invoice_id = next(
        eid
        for eid, record in truth.items()
        if record["category"] == "INVOICE_QUERY" and verify_edges.PHRASE_RX.search(emails[eid]["body"])
    )
    submission[invoice_id] = {
        "category": "INVOICE_QUERY",
        "status": "NEEDS_REVIEW",
        "review_reason": "missing_attachment",
        "defect_fields": [],
        "has_defect": False,
    }
    failures = verify_edges.check_phrase_negatives(submission, truth, emails)
    assert any(invoice_id in failure for failure in failures)


def test_defect_checker_catches_a_wrong_field_set(dataset):
    emails, truth = dataset
    submission = golden_submission(truth, emails)
    submission["email_004"]["defect_fields"] = ["consignee"]
    failures = verify_edges.check_defects(submission, "all")
    assert any("email_004" in failure for failure in failures)


def test_defect_checker_scope_txt_skips_binary(dataset):
    emails, truth = dataset
    submission = golden_submission(truth, emails)
    for email_id in verify_edges.BINARY_DEFECTS:
        submission[email_id] = default_submission_record(category="BL_COMPARISON")
    assert verify_edges.check_defects(submission, "txt") == []
    assert verify_edges.check_defects(submission, "all") != []


def test_zero_attachment_checker_catches_a_missing_escalation(dataset):
    emails, truth = dataset
    submission = golden_submission(truth, emails)
    submission["email_506"] = default_submission_record(category="BL_COMPARISON")
    failures = verify_edges.check_zero_attachment_bls(submission, truth, emails)
    assert any("email_506" in failure for failure in failures)


def test_structural_compare_field_rules():
    from tools.verify_extraction import compare_field

    assert compare_field(1, 1.0, "container_count")
    assert not compare_field(1, 2, "container_count")
    assert compare_field("PORT KLANG (WESTPORT), MALAYSIA", "PORT KLANG, MALAYSIA", "port_of_loading")
    assert not compare_field("SINGAPORE", "BUSAN", "port_of_loading")
    assert compare_field(None, None, "consignee")
    assert not compare_field(None, "ACME", "consignee")
    assert compare_field("APRIL FINE PAPER TRADING", "april fine paper trading", "shipper")
