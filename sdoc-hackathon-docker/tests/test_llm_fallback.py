from __future__ import annotations

import importlib

from app.schema import COMPARE_FIELDS


def _fields():
    return {field: None for field in COMPARE_FIELDS}


def _reload(monkeypatch, tmp_path):
    from app import state

    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    monkeypatch.delenv("SCORED_RUN", raising=False)
    importlib.reload(state)
    import app.extensions.llm_label_fallback as fallback

    return importlib.reload(fallback)


def test_accepts_high_confidence_type_compatible_mapping(monkeypatch, tmp_path):
    fallback = _reload(monkeypatch, tmp_path)

    result = fallback.map_label(
        "Loading Port",
        "PORT KLANG",
        _fields(),
        lambda _prompt: {"field": "port_of_loading", "confidence": 0.95},
    )

    assert result == {"field": "port_of_loading", "confidence": 0.95, "accepted": True}


def test_rejects_low_confidence(monkeypatch, tmp_path):
    fallback = _reload(monkeypatch, tmp_path)

    result = fallback.map_label(
        "Loading Port",
        "PORT KLANG",
        _fields(),
        lambda _prompt: {"field": "port_of_loading", "confidence": 0.5},
    )

    assert result["field"] is None
    assert not result["accepted"]


def test_known_non_field_is_ineligible(monkeypatch, tmp_path):
    fallback = _reload(monkeypatch, tmp_path)

    result = fallback.map_label(
        "NET WEIGHT",
        "100 KG",
        _fields(),
        lambda _prompt: {"field": "gross_weight_kg", "confidence": 1.0},
    )

    assert result["reason"] == "ineligible"


def test_malformed_response_declines(monkeypatch, tmp_path):
    fallback = _reload(monkeypatch, tmp_path)

    result = fallback.map_label("Loading Port", "PORT KLANG", _fields(), lambda _prompt: "not json")

    assert result["field"] is None
    assert not result["accepted"]


def test_client_failure_declines(monkeypatch, tmp_path):
    fallback = _reload(monkeypatch, tmp_path)

    def fail(_prompt):
        raise TimeoutError("boom")

    result = fallback.map_label("Loading Port", "PORT KLANG", _fields(), fail)

    assert result["field"] is None
    assert not result["accepted"]
