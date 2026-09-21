"""Preflight contract tests (plan 06 §3)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.schema import default_submission_record  # noqa: E402
from tools import preflight  # noqa: E402

DATA_DIR = PROJECT_DIR / "data_v2"


def inbox_ids() -> set[str]:
    return {p.stem for p in (DATA_DIR / "inbox").glob("email_*.json")}


def valid_submission() -> dict:
    return {email_id: default_submission_record() for email_id in sorted(inbox_ids())}


def test_check_structure_accepts_a_complete_submission():
    assert preflight.check_structure(valid_submission(), inbox_ids()) == []


def test_check_structure_flags_wrong_key_count():
    submission = valid_submission()
    submission.pop("email_001")
    problems = preflight.check_structure(submission, None)
    assert any("520" in problem for problem in problems)


def test_check_structure_flags_missing_ids():
    submission = valid_submission()
    submission["email_999"] = submission.pop("email_001")
    problems = preflight.check_structure(submission, inbox_ids())
    assert any("missing" in problem for problem in problems)
    assert any("unexpected" in problem for problem in problems)


def test_check_structure_flags_invariant_violation():
    submission = valid_submission()
    submission["email_001"] = {
        "category": "BL_COMPARISON",
        "status": "MISMATCH",
        "review_reason": None,
        "defect_fields": [],
        "has_defect": True,
    }
    problems = preflight.check_structure(submission, inbox_ids())
    assert any("email_001" in problem for problem in problems)


def test_offline_preflight_runs_green_on_a_real_submission(tmp_path):
    from app import run as run_module

    out = tmp_path / "submission.json"
    run_module.run(data_dir=DATA_DIR, out_path=out, use_checkpoint=False)
    assert preflight.main([str(out), "--data", str(DATA_DIR)]) == 0


def test_offline_preflight_fails_on_a_broken_submission(tmp_path):
    submission = valid_submission()
    submission.pop("email_001")
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(submission), encoding="utf-8")
    assert preflight.main([str(path), "--data", str(DATA_DIR)]) == 1


def test_preflight_reports_unreadable_file(tmp_path):
    assert preflight.main([str(tmp_path / "nope.json")]) == 2


def test_sample_baseline_constant_matches_the_harness():
    """The dry-run baseline is the documented all-GENERAL score."""
    truth = json.loads((DATA_DIR / "ground_truth.json").read_text(encoding="utf-8"))
    from tools.score_local import load_scoring

    board = load_scoring().score_all(truth, valid_submission())
    assert board["final_score"] == pytest.approx(preflight.SAMPLE_BASELINE, abs=1e-3)
