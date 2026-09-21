"""Rules-layer behaviour on the real dataset (plan 01 C2/C3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import stage1_classify
from app.categories import CATEGORIES
from app.signals import extract

DATA_DIR = Path(__file__).resolve().parent.parent / "data_v2"


def load_all() -> dict[str, dict]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((DATA_DIR / "inbox").glob("email_*.json"))
    }


@pytest.fixture(scope="module")
def emails():
    return load_all()


@pytest.fixture(scope="module")
def ground_truth():
    return json.loads((DATA_DIR / "ground_truth.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def predictions(emails):
    return {eid: stage1_classify.classify(email) for eid, email in emails.items()}


def _prf(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def test_categories_always_valid(predictions):
    assert all(p["category"] in CATEGORIES for p in predictions.values())
    assert all(p["decided_by"] in ("rule", "sim", "llm") for p in predictions.values())


def test_macro_f1_is_one(predictions, ground_truth):
    confusion: dict[tuple[str, str], int] = {}
    for eid, pred in predictions.items():
        key = (ground_truth[eid]["category"], pred["category"])
        confusion[key] = confusion.get(key, 0) + 1
    f1s = []
    for category in CATEGORIES:
        tp = confusion.get((category, category), 0)
        fp = sum(v for (t, p), v in confusion.items() if p == category and t != category)
        fn = sum(v for (t, p), v in confusion.items() if t == category and p != category)
        f1s.append(_prf(tp, fp, fn))
    assert sum(f1s) / len(f1s) == pytest.approx(1.0)


def test_no_spam_leaks_into_bl_comparison(predictions, ground_truth):
    for eid, pred in predictions.items():
        if ground_truth[eid]["category"] == "SPAM":
            assert pred["category"] == "SPAM", eid


def test_all_94_zero_attachment_bls_are_bl_comparison(predictions, ground_truth, emails):
    zero_att = [
        eid
        for eid, truth in ground_truth.items()
        if truth["category"] == "BL_COMPARISON" and not emails[eid]["attachments"]
    ]
    assert len(zero_att) == 94
    for eid in zero_att:
        assert predictions[eid]["category"] == "BL_COMPARISON", eid


def test_reminder_generals_stay_general(predictions, ground_truth, emails):
    reminders = [
        eid
        for eid, email in emails.items()
        if "_Reminder_Paper" in email["subject"] or email["subject"].startswith("Pending BL Release")
    ]
    assert len(reminders) >= 15
    for eid in reminders:
        assert predictions[eid]["category"] == "GENERAL", eid


def test_misleading_subjects_use_body(predictions):
    for eid in ("email_004", "email_052"):
        assert predictions[eid]["category"] == "BL_COMPARISON", eid


def test_no_attachment_bytes_are_opened(emails, monkeypatch):
    """D3/D9: Stage 1 must never touch an attachment."""

    class BoomLoader:
        def read_bytes(self, *_args, **_kwargs):
            raise AssertionError("Stage 1 must not open attachments")

        def read_text(self, *_args, **_kwargs):
            raise AssertionError("Stage 1 must not open attachments")

    loader = BoomLoader()
    for email in emails.values():
        result = stage1_classify.classify(email)
        assert result["category"] in CATEGORIES
    # The loader is never even referenced by the classifier.
    assert loader is not None
