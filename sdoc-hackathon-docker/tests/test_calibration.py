"""Calibration behaviour: thresholds and the frozen cache (plan 01 C6)."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from app import llm_client, stage1_classify, state
from app.categories import CATEGORIES
from app.loader_client import LoaderClient
from app.signals import extract

DATA_DIR = Path(__file__).resolve().parent.parent / "data_v2"


@pytest.fixture()
def frozen(tmp_path, monkeypatch):
    """A frozen run replaying the committed cache from a temp state dir.

    The committed ``state/llm_cache.json`` is copied in, exactly as the frozen
    submission replays it — the point is that no network call is needed.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    committed = Path(__file__).resolve().parent.parent / "state" / "llm_cache.json"
    if committed.is_file():
        (state_dir / "llm_cache.json").write_bytes(committed.read_bytes())

    monkeypatch.setenv("STATE_DIR", str(state_dir))
    monkeypatch.setenv("SCORED_RUN", "1")
    importlib.reload(state)
    importlib.reload(llm_client)
    yield state_dir
    monkeypatch.delenv("SCORED_RUN", raising=False)
    importlib.reload(state)
    importlib.reload(llm_client)


def test_evidence_threshold_is_monotonic():
    """Tightening the accept margin never increases the evidence layer's share."""
    email = {"subject": "s", "body": "b"}
    signals = extract(email)
    votes = stage1_classify.evidence_votes(signals)
    margins = []
    original = stage1_classify.ACCEPT_MARGIN
    try:
        for margin in (0.5, 1.0, 2.0, 4.0, 100.0):
            stage1_classify.ACCEPT_MARGIN = margin
            decision = stage1_classify.decide_by_evidence(votes)
            margins.append(decision is not None)
    finally:
        stage1_classify.ACCEPT_MARGIN = original
    assert margins == sorted(margins, reverse=True), "acceptance must fall as the margin grows"


def test_similarity_threshold_holds_on_clean_examples():
    for email_id in ("email_001", "email_008", "email_494", "email_012"):
        email = json.loads((DATA_DIR / "inbox" / f"{email_id}.json").read_text(encoding="utf-8"))
        result = stage1_classify.classify_by_similarity(
            extract(email), email["body"], email["subject"]
        )
        if result is not None:
            assert result.category in CATEGORIES
            assert result.confidence >= stage1_classify.SIM_THRESHOLD


def test_frozen_cache_is_recorded_and_committed():
    """DoD: ``state/llm_cache.json`` exists and is deterministic."""
    cache_path = Path(__file__).resolve().parent.parent / "state" / "llm_cache.json"
    if not cache_path.is_file():
        pytest.skip("llm_cache.json not recorded in this checkout")
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert isinstance(cache, dict)
    for key, value in cache.items():
        assert len(key) == 64, "cache key must be sha256(subject+body)"
        assert value["category"] in CATEGORIES
    # Re-recording with the same inputs yields the same file bytes.
    before = cache_path.read_bytes()
    llm_client.save_cache(cache, cache_path)
    assert cache_path.read_bytes() == before


def test_frozen_run_replays_cache_without_network(frozen, monkeypatch):
    cache = {llm_client.cache_key("S", "B"): {"category": "SPAM", "confidence": 1.0}}
    llm_client.save_cache(cache)

    def boom(*_args, **_kwargs):
        raise AssertionError("frozen run must not touch the network")

    monkeypatch.setattr(llm_client, "_live_call", boom)
    assert llm_client.classify({"subject": "S", "body": "B"})["category"] == "SPAM"


def test_frozen_macro_f1_meets_gate(frozen):
    """W1 gate: rules + sim + frozen cache, no live LLM."""
    if not (DATA_DIR / "inbox").is_dir():
        pytest.skip("data_v2 not available")
    client = LoaderClient(DATA_DIR)
    ground_truth = json.loads((DATA_DIR / "ground_truth.json").read_text(encoding="utf-8"))

    confusion: dict[tuple[str, str], int] = {}
    layers: dict[str, int] = {}
    for email in client.emails():
        result = stage1_classify.classify(email)
        layers[result["_stage1"]["layer"]] = layers.get(result["_stage1"]["layer"], 0) + 1
        key = (ground_truth[email["email_id"]]["category"], result["category"])
        confusion[key] = confusion.get(key, 0) + 1

    def prf(tp, fp, fn):
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        return 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    f1s = []
    for category in CATEGORIES:
        tp = confusion.get((category, category), 0)
        fp = sum(v for (t, p), v in confusion.items() if p == category and t != category)
        fn = sum(v for (t, p), v in confusion.items() if t == category and p != category)
        f1s.append(prf(tp, fp, fn))
    macro_f1 = sum(f1s) / len(f1s)
    accuracy = sum(v for (t, p), v in confusion.items() if t == p) / len(client.emails())

    assert macro_f1 >= 0.95, f"macro_f1={macro_f1} layers={layers}"
    assert accuracy >= 0.95, f"accuracy={accuracy}"
    assert "llm" in layers, "the frozen cache must actually be replayed"
