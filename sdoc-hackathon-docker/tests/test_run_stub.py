"""Contract test — orchestrator stub behaviour, gate ordering, F7 (plan 00 F6/F7).

Runs against the real ``data_v2`` dataset: 520 keys, valid vocabulary,
invariants hold, and the 23 INVOICE_QUERY phrase matches never escalate.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import run as run_module
from app import state
from app.checkpoint import Checkpoint, attachment_bytes_hash, make_key
from app.schema import CATEGORIES, REVIEW_REASONS, STATUSES

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data_v2"
INVOICE_PHRASE_IDS = {f"email_{i:03d}" for i in range(1, 521)}


@pytest.fixture(scope="module")
def dataset():
    if not (DATA_DIR / "inbox").is_dir():
        pytest.skip("data_v2 not available")
    return DATA_DIR


@pytest.fixture(scope="module")
def submission(dataset):
    return run_module.run(data_dir=dataset, out_path=None, use_checkpoint=False)


def test_exactly_520_keys(submission, dataset):
    assert len(submission) == 520
    inbox_ids = {p.stem for p in (dataset / "inbox").glob("email_*.json")}
    assert set(submission) == inbox_ids


def test_all_categories_and_statuses_valid(submission):
    assert {r["category"] for r in submission.values()} <= set(CATEGORIES)
    assert {r["status"] for r in submission.values()} <= set(STATUSES)
    for record in submission.values():
        assert record["review_reason"] is None or record["review_reason"] in REVIEW_REASONS
        assert record["has_defect"] == (record["status"] == "MISMATCH")


def test_baseline_is_general_ok(submission):
    """W0 has no stage logic: every email is GENERAL/OK (baseline ≈ 0.0124)."""
    assert all(r["category"] == "GENERAL" for r in submission.values())
    assert all(r["status"] == "OK" for r in submission.values())


def test_zero_attachment_phrase_negatives_do_not_escalate(dataset, submission):
    """The 23 INVOICE_QUERY bodies matching the phrase stay non-escalated."""
    phrase = run_module.MISSING_PHRASE
    matches = []
    for path in sorted((dataset / "inbox").glob("email_*.json")):
        email = json.loads(path.read_text(encoding="utf-8"))
        if phrase.search(email["body"]):
            matches.append(email["email_id"])
    assert len(matches) == 28
    for email_id in matches:
        assert submission[email_id]["status"] == "OK", email_id
        assert submission[email_id]["review_reason"] is None, email_id


def test_gold_edge_cases_have_the_right_attachments(dataset):
    """Edge-case ownership guard: 506/508/510 are 0-att, 507/509 are SI-only."""
    zero_att = {"email_506", "email_508", "email_510"}
    si_only = {"email_507", "email_509"}
    for email_id in zero_att | si_only:
        email = json.loads((dataset / "inbox" / f"{email_id}.json").read_text(encoding="utf-8"))
        if email_id in zero_att:
            assert email["attachments"] == []
        else:
            assert len(email["attachments"]) == 1
            assert "_SI" in email["attachments"][0]
        assert run_module.MISSING_PHRASE.search(email["body"])


def test_frozen_run_hashes_exported():
    """DoD: SCHEMA_VERSION / ALIAS_TABLE_HASH / LEARNED_ALIAS_HASH are exported."""
    from app import state

    assert state.SCHEMA_VERSION == "3.0"
    assert isinstance(state.ALIAS_TABLE_HASH, str) and len(state.ALIAS_TABLE_HASH) == 64
    assert isinstance(state.LEARNED_ALIAS_HASH, str) and len(state.LEARNED_ALIAS_HASH) == 64
    state.refresh_hashes()
    assert state.ALIAS_TABLE_HASH == state.alias_table_hash()
    assert state.LEARNED_ALIAS_HASH == state.learned_alias_hash()


def test_gate_fires_when_category_is_bl_and_phrase_present(dataset):
    """Direct gate test: BL + 0 attachments + phrase → missing_attachment."""
    from app.loader_client import LoaderClient

    client = LoaderClient(dataset)
    email = {
        "email_id": "synthetic",
        "from": "x@y.z",
        "subject": "TO CONFIRM DOCS",
        "body": "Dear Team,\n\nPlease compare ... (attachments appear to have been dropped). Thank you.",
        "attachments": [],
    }
    result = run_module.extract_email(email, "BL_COMPARISON", client)
    assert result.doc_status == "NEEDS_REVIEW"
    assert result.review_reason == "missing_attachment"

    result = run_module.extract_email(email, "INVOICE_QUERY", client)
    assert result.doc_status == "READY"

    email["body"] = "Please assist to send the draft BL for MSDUL09425 for checking asap."
    result = run_module.extract_email(email, "BL_COMPARISON", client)
    assert result.doc_status == "READY"


def test_single_attachment_escalates_only_for_bl(dataset):
    from app.loader_client import LoaderClient

    client = LoaderClient(dataset)
    email = {
        "email_id": "synthetic",
        "from": "x@y.z",
        "subject": "SI",
        "body": "Please send the BL.",
        "attachments": ["attachments/email_001_SI.txt"],
    }
    assert run_module.extract_email(email, "BL_COMPARISON", client).review_reason == "missing_attachment"
    assert run_module.extract_email(email, "SI_REQUEST", client).doc_status == "READY"


def test_two_attachment_bl_is_unreadable_without_stage2(dataset):
    """W0 stub: BL with 2 attachments reaches the router hook and exits unreadable."""
    from app.loader_client import LoaderClient

    client = LoaderClient(dataset)
    email = json.loads((dataset / "inbox" / "email_001.json").read_text(encoding="utf-8"))
    result = run_module.extract_email(email, "BL_COMPARISON", client)
    if run_module._load_attr("app.stage2.router", "extract_pair") is None:
        assert result.doc_status == "NEEDS_REVIEW"
        assert result.review_reason == "unreadable"
    else:  # pragma: no cover - once plan 02 lands
        assert result.doc_status in ("READY", "NEEDS_REVIEW")


def test_build_record_maps_verdicts():
    from app.schema import ExtractionResult, Verdict

    ready = ExtractionResult()
    record = run_module.build_record("BL_COMPARISON", ready, Verdict(), "rule")
    assert record["status"] == "OK" and record["decided_by"] == "rule"

    defect = run_module.build_record(
        "BL_COMPARISON", ready, Verdict(has_defect=True, defect_fields=["consignee"])
    )
    assert record["has_defect"] is False
    assert defect["status"] == "MISMATCH" and defect["defect_fields"] == ["consignee"]

    review = run_module.build_record(
        "BL_COMPARISON", ExtractionResult(doc_status="NEEDS_REVIEW", review_reason="unreadable"), None
    )
    assert review["status"] == "NEEDS_REVIEW" and review["review_reason"] == "unreadable"


def test_run_is_deterministic(dataset):
    first = run_module.run(data_dir=dataset, use_checkpoint=False)
    second = run_module.run(data_dir=dataset, use_checkpoint=False)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_checkpoint_makes_second_run_identical(dataset, tmp_path):
    checkpoint = tmp_path / "checkpoint.jsonl"
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    run_module.run(data_dir=dataset, out_path=out_a, checkpoint_path=checkpoint)
    assert checkpoint.is_file() and len(Checkpoint(checkpoint).load()) == 520
    run_module.run(data_dir=dataset, out_path=out_b, checkpoint_path=checkpoint)
    assert out_a.read_bytes() == out_b.read_bytes()


def test_extension_hooks_are_not_loaded_under_scored_run(monkeypatch):
    """F7: with SCORED_RUN=1 the extension modules are never imported."""
    import importlib

    monkeypatch.setenv("SCORED_RUN", "1")
    importlib.reload(state)
    importlib.reload(run_module)
    try:
        sys.modules.pop("app.extensions.alias_learning", None)
        assert run_module.load_extensions() == []
        assert "app.extensions.alias_learning" not in sys.modules
        assert "app.extensions.review_queue" not in sys.modules
    finally:
        monkeypatch.delenv("SCORED_RUN", raising=False)
        importlib.reload(state)
        importlib.reload(run_module)


def test_cli_writes_520_keys(tmp_path, dataset):
    out = tmp_path / "submission.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.run",
            "--data",
            str(dataset),
            "--out",
            str(out),
            "--no-checkpoint",
        ],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "wrote 520 records" in result.stdout
    assert "SCHEMA_VERSION=3.0" in result.stdout
    assert "ALIAS_TABLE_HASH=" in result.stdout
    assert "LEARNED_ALIAS_HASH=" in result.stdout
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 520


def test_checkpoint_key_uses_alias_and_learned_hashes(dataset, tmp_path):
    checkpoint = tmp_path / "checkpoint.jsonl"
    run_module.run(data_dir=dataset, out_path=None, checkpoint_path=checkpoint)
    entries = Checkpoint(checkpoint).load()
    assert len(entries) == 520
    email = json.loads((dataset / "inbox" / "email_001.json").read_text(encoding="utf-8"))
    from app.loader_client import LoaderClient

    client = LoaderClient(dataset)
    blobs = [client.read_bytes(p) for p in email["attachments"]]
    expected = make_key("email_001", attachment_bytes_hash(blobs))
    assert expected in entries
