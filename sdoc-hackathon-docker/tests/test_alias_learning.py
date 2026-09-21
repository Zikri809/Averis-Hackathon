from __future__ import annotations

import importlib
import threading


def _reload(monkeypatch, tmp_path):
    from app import state

    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    monkeypatch.delenv("SCORED_RUN", raising=False)
    importlib.reload(state)
    import app.extensions.alias_learning as alias_learning

    return importlib.reload(alias_learning)


def test_rejects_known_non_field_label(monkeypatch, tmp_path):
    alias_learning = _reload(monkeypatch, tmp_path)

    ok, reason = alias_learning.validate("NET WEIGHT", "gross_weight_kg")

    assert not ok
    assert "known non-field" in reason


def test_generated_alias_precedence(monkeypatch, tmp_path):
    alias_learning = _reload(monkeypatch, tmp_path)

    assert alias_learning.merged_aliases()["SHIPPER"] == "shipper"
    ok, reason = alias_learning.validate("Shipper", "consignee")

    assert not ok
    assert "collides" in reason


def test_two_phase_loads_only_confirmed(monkeypatch, tmp_path):
    alias_learning = _reload(monkeypatch, tmp_path)

    alias_learning.propose("Loading Port", "port_of_loading")
    assert "LOADING PORT" not in alias_learning.load()

    alias_learning.confirm("Loading Port", "port_of_loading")
    assert alias_learning.load()["LOADING PORT"] == "port_of_loading"


def test_concurrent_confirm_writes_are_preserved(monkeypatch, tmp_path):
    alias_learning = _reload(monkeypatch, tmp_path)

    threads = [
        threading.Thread(target=alias_learning.confirm, args=(f"Demo Alias {idx}", "shipper"))
        for idx in range(5)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    learned = alias_learning.load()
    for idx in range(5):
        assert learned[f"DEMO ALIAS {idx}"] == "shipper"
