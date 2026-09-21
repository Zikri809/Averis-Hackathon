"""LLM client behaviour with a mocked transport (plan 01 C5)."""
from __future__ import annotations

import importlib
import json

import pytest

from app import llm_client
from app import state


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SCORED_RUN", "0")
    importlib.reload(state)
    importlib.reload(llm_client)
    yield
    monkeypatch.delenv("SCORED_RUN", raising=False)
    importlib.reload(state)
    importlib.reload(llm_client)


def test_cache_key_is_sha256_of_subject_plus_body():
    import hashlib

    key = llm_client.cache_key("S", "B")
    assert key == hashlib.sha256(b"SB").hexdigest()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"category": "SPAM", "confidence": 0.9}', "SPAM"),
        ('```json\n{"category": "GENERAL", "confidence": 1}\n```', "GENERAL"),
        ('Sure! {"category": "SI_REQUEST", "confidence": 0.8} hope that helps', "SI_REQUEST"),
        ("not json at all", None),
        ("", None),
    ],
)
def test_extract_json_handles_fenced_and_truncated(raw, expected):
    parsed = llm_client.extract_json(raw)
    assert (parsed or {}).get("category") == expected


def test_live_call_is_cached_and_replayed(monkeypatch):
    calls = []

    def fake_call(email, timeout=llm_client.DEFAULT_TIMEOUT):
        calls.append(email["email_id"])
        return '{"category": "BL_COMPARISON", "confidence": 0.95}'

    monkeypatch.setattr(llm_client, "_live_call", fake_call)
    email = {"email_id": "email_001", "subject": "S", "body": "B"}

    first = llm_client.classify(email)
    assert first["category"] == "BL_COMPARISON"
    assert len(calls) == 1

    second = llm_client.classify(email)
    assert second["category"] == "BL_COMPARISON"
    assert len(calls) == 1, "second call must be served from the cache"

    assert state.llm_cache_path().is_file()


def test_malformed_json_retries_once_then_gives_up(monkeypatch):
    calls = []

    def fake_call(email, timeout=llm_client.DEFAULT_TIMEOUT):
        calls.append(1)
        return "definitely not json"

    monkeypatch.setattr(llm_client, "_live_call", fake_call)
    assert llm_client.classify({"subject": "S", "body": "B"}) is None
    assert len(calls) == 2, "exactly one retry"


def test_scored_run_is_cache_only(monkeypatch, tmp_path):
    monkeypatch.setenv("SCORED_RUN", "1")
    importlib.reload(state)
    importlib.reload(llm_client)

    def boom(*_args, **_kwargs):
        raise AssertionError("frozen run must never call the network")

    monkeypatch.setattr(llm_client, "_live_call", boom)
    assert llm_client.classify({"subject": "S", "body": "B"}) is None
    # A cache hit still replays under SCORED_RUN=1 (no network needed).
    llm_client.save_cache({llm_client.cache_key("S", "B"): {"category": "SPAM", "confidence": 1.0}})
    assert llm_client.classify({"subject": "S", "body": "B"})["category"] == "SPAM"


def test_scored_run_replays_a_recorded_cache(monkeypatch):
    email = {"subject": "S", "body": "B"}
    cache = {llm_client.cache_key("S", "B"): {"category": "SPAM", "confidence": 0.9}}
    llm_client.save_cache(cache)

    monkeypatch.setenv("SCORED_RUN", "1")
    importlib.reload(state)
    importlib.reload(llm_client)

    assert llm_client.classify(email)["category"] == "SPAM"


def test_http_error_is_swallowed(monkeypatch):
    import urllib.error

    def fake_post(*_args, **_kwargs):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(llm_client, "_post", fake_post)
    monkeypatch.setenv("KENARI_API_KEY", "test-key")
    assert llm_client._live_call({"subject": "S", "body": "B"}) is None


def test_api_key_is_read_from_environment(monkeypatch):
    monkeypatch.delenv("KENARI_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)
    assert llm_client.api_key() is None
    monkeypatch.setenv("KENARI_API_KEY", "kn-test")
    assert llm_client.api_key() == "kn-test"


def test_default_endpoint_is_kenari_glm():
    assert llm_client.DEFAULT_BASE_URL == "https://kenari.id/v1"
    assert llm_client.DEFAULT_MODEL == "glm-5-3-flash"
