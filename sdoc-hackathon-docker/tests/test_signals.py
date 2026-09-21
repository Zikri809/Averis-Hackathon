"""Signal extraction tests on real emails (plan 01 C1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import signals

DATA_DIR = Path(__file__).resolve().parent.parent / "data_v2"


def load(email_id: str) -> dict:
    return json.loads((DATA_DIR / "inbox" / f"{email_id}.json").read_text(encoding="utf-8"))


def test_has_si_has_bl_and_counts():
    email = load("email_001")
    sig = signals.extract(email)
    assert sig.has_SI and sig.has_BL
    assert sig.n_att == 2
    assert sig.is_internal_sender is False
    assert sig.sender_domain == "safqa.co.ke"


def test_clean_comparison_intent():
    sig = signals.extract(load("email_001"))
    assert sig.draft_bl and sig.check_bl and sig.si_bl_pair
    assert signals.intent_check(sig) is True
    assert sig.billing_terms is False
    assert sig.spam is False


def test_misleading_subject_004_uses_body():
    """004's subject says REQUEST BL DRAFT; the body is a comparison request."""
    email = load("email_004")
    sig = signals.extract(email)
    assert "REQUEST BL DRAFT" in email["subject"]
    assert signals.intent_check(sig) is True


def test_zero_attachment_bl_495_still_intent_check():
    """495 is a zero-attachment BL request that must still read as comparison."""
    email = load("email_495")
    sig = signals.extract(email)
    assert sig.n_att == 0
    assert sig.draft_bl
    assert signals.intent_check(sig) is True
    assert sig.billing_terms is False


def test_missing_attachment_phrase_506():
    email = load("email_506")
    sig = signals.extract(email)
    assert sig.n_att == 0
    assert signals.missing_attachment_phrase(email["body"]) is True
    assert sig.draft_bl and sig.check_bl


def test_invoice_query_phrase_match_is_billing():
    """The 23 INVOICE_QUERY bodies matching dropped/still missing are billing."""
    candidates = []
    for path in sorted((DATA_DIR / "inbox").glob("email_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if signals.missing_attachment_phrase(record["body"]):
            candidates.append(record)
    assert len(candidates) == 28
    invoice_like = [r for r in candidates if "invoice" in r["body"].lower()]
    assert len(invoice_like) == 23
    for record in invoice_like:
        assert signals.extract(record).billing_terms is True


def test_spam_bank_details_emails():
    """The 2 SPAM 'bank details' mails score as spam despite billing words."""
    spam_records = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((DATA_DIR / "inbox").glob("email_*.json"))
    ]
    bank = [r for r in spam_records if "bank details" in r["body"] or "bank officer" in r["body"]]
    assert bank
    for record in bank:
        assert signals.extract(record).spam is True


def test_reminder_generals_stay_non_doc():
    """The reminder subjects/bodies are broadcast notices, not directed asks."""
    reminders = []
    for path in sorted((DATA_DIR / "inbox").glob("email_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if "_Reminder_Paper" in record["subject"] or record["subject"].startswith("Pending BL Release"):
            reminders.append(record)
    assert len(reminders) >= 15
    for record in reminders:
        sig = signals.extract(record)
        assert sig.reminder is True
        assert signals.intent_check(sig) is False


def test_si_body_template_signals():
    sig = signals.extract(load("email_008"))
    assert sig.si_for is True
    assert sig.si_detail is True
    assert signals.intent_create(sig) is True
    assert sig.has_SI is False  # no attachments: the body *is* the SI
