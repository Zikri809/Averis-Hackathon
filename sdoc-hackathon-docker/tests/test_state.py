"""Contract test — state paths, hashes, and the 520-key assert (plan 00 F5)."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from app import state
from app.schema import default_submission_record


def _submission(n: int = 520, ids=None) -> dict:
    ids = ids or [f"email_{i:03d}" for i in range(1, n + 1)]
    return {email_id: default_submission_record() for email_id in ids}


def test_scored_run_default_is_off():
    assert state.SCORED_RUN is False
    assert state.SCORED_RUN is (__import__("os").environ.get("SCORED_RUN", "0") == "1")


def test_paths_resolve_and_llm_cache_path(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    importlib.reload(state)
    assert state.llm_cache_path() == tmp_path / "state" / "llm_cache.json"
    assert state.checkpoint_path() == tmp_path / "state" / "checkpoint.jsonl"
    assert state.alias_learned_path() == tmp_path / "state" / "alias_learned.jsonl"
    importlib.reload(state)


def test_env_overrides_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    importlib.reload(state)
    assert state.DATA_DIR == tmp_path / "data"
    importlib.reload(state)


def test_assert_520_accepts_valid_submission():
    assert state.assert_520(_submission()) is True


def test_assert_520_rejects_wrong_key_count():
    with pytest.raises(AssertionError, match="520"):
        state.assert_520(_submission(519))


def test_assert_520_rejects_key_mismatch():
    submission = _submission()
    submission["email_999"] = submission.pop("email_001")
    with pytest.raises(AssertionError, match="inbox ids"):
        state.assert_520(submission, email_ids=[f"email_{i:03d}" for i in range(1, 521)])


def test_assert_520_rejects_contract_violation():
    submission = _submission()
    submission["email_001"] = {
        "category": "BL_COMPARISON",
        "status": "MISMATCH",
        "review_reason": None,
        "defect_fields": [],
        "has_defect": True,
    }
    with pytest.raises(AssertionError, match="contract"):
        state.assert_520(submission)


def test_assert_520_accepts_needs_review_records():
    submission = _submission()
    submission["email_001"] = {
        "category": "BL_COMPARISON",
        "status": "NEEDS_REVIEW",
        "review_reason": "unreadable",
        "defect_fields": [],
        "has_defect": False,
    }
    assert state.assert_520(submission) is True


def test_alias_table_hash_resolves_to_the_published_table():
    """W0 falls back to the empty hash; once plan 02 lands it is the real table."""
    from app.normalize import empty_hash

    digest = state.alias_table_hash()
    assert len(digest) == 64
    try:
        from app.stage2.aliases import ALIAS_TABLE_HASH

        assert digest == ALIAS_TABLE_HASH
    except ImportError:  # pragma: no cover - W0 only
        assert digest == empty_hash()


def test_learned_alias_hash_is_empty_hash_without_file(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    importlib.reload(state)
    from app.normalize import empty_hash

    assert state.learned_alias_hash() == empty_hash()
    importlib.reload(state)


def test_write_submission_is_atomic(tmp_path):
    from app.loader_client import LoaderClient

    data = tmp_path / "data"
    (data / "inbox").mkdir(parents=True)
    (data / "attachments").mkdir(parents=True)
    (data / "inbox" / "email_001.json").write_text(
        json.dumps({"email_id": "email_001", "from": "", "subject": "", "body": "", "attachments": []}),
        encoding="utf-8",
    )
    client = LoaderClient(data)
    out = client.write_submission({"email_001": default_submission_record()}, tmp_path / "sub.json")
    assert out.is_file()
    assert not (tmp_path / "sub.json.tmp").exists()
    assert json.loads(out.read_text(encoding="utf-8"))["email_001"]["status"] == "OK"
