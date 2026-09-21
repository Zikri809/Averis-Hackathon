"""Contract test — checkpoint key, resume, invalidation (plan 00 F4)."""
from __future__ import annotations

import json

import pytest

from app import state
from app.checkpoint import Checkpoint, attachment_bytes_hash, make_key
from app.normalize import empty_hash


def _client(tmp_path):
    """A synthetic 520-email dataset (the run contract requires exactly 520)."""
    from app.loader_client import LoaderClient

    data = tmp_path / "data"
    (data / "inbox").mkdir(parents=True)
    (data / "attachments").mkdir(parents=True)
    for i in range(1, 521):
        email_id = f"email_{i:03d}"
        (data / "inbox" / f"{email_id}.json").write_text(
            json.dumps(
                {
                    "email_id": email_id,
                    "from": "a@b.c",
                    "subject": "s",
                    "body": "b",
                    "attachments": [f"attachments/{email_id}_SI.txt"],
                }
            ),
            encoding="utf-8",
        )
        (data / "attachments" / f"{email_id}_SI.txt").write_text(
            "SHIPPING INSTRUCTION\n", encoding="utf-8"
        )
    return LoaderClient(data)


def test_key_components_and_stability():
    key = make_key("email_001", "abc", alias_table_hash="alias", learned_alias_hash="learned", schema_version="3.0")
    assert key == make_key("email_001", "abc", alias_table_hash="alias", learned_alias_hash="learned", schema_version="3.0")
    assert key != make_key("email_002", "abc", alias_table_hash="alias", learned_alias_hash="learned", schema_version="3.0")
    assert key != make_key("email_001", "abd", alias_table_hash="alias", learned_alias_hash="learned", schema_version="3.0")
    assert key != make_key("email_001", "abc", alias_table_hash="other", learned_alias_hash="learned", schema_version="3.0")
    assert key != make_key("email_001", "abc", alias_table_hash="alias", learned_alias_hash="other", schema_version="3.0")
    assert key != make_key("email_001", "abc", alias_table_hash="alias", learned_alias_hash="learned", schema_version="3.1")


def test_key_defaults_use_the_resolved_hashes(monkeypatch, tmp_path):
    """Defaults are ``state.alias_table_hash()``/``learned_alias_hash()``.

    At W0 those are the empty hash; once plan 02 lands the alias-table hash is
    the real table — either way the defaults must match the resolvers.
    """
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SCORED_RUN", "0")
    import importlib

    importlib.reload(state)
    key = make_key("email_001", "")
    assert key == make_key(
        "email_001",
        empty_hash(),
        alias_table_hash=state.alias_table_hash(),
        learned_alias_hash=state.learned_alias_hash(),
        schema_version="3.0",
    )
    importlib.reload(state)


def test_attachment_bytes_hash_is_order_independent():
    assert attachment_bytes_hash([b"a", b"b"]) == attachment_bytes_hash([b"b", b"a"])
    assert attachment_bytes_hash([b"a"]) != attachment_bytes_hash([b"a", b"b"])


def test_put_flush_load_roundtrip(tmp_path):
    path = tmp_path / "checkpoint.jsonl"
    checkpoint = Checkpoint(path)
    checkpoint.put("k1", {"status": "OK"})
    checkpoint.flush()
    assert path.is_file()

    reloaded = Checkpoint(path)
    assert reloaded.load() == {"k1": {"status": "OK"}}
    assert reloaded.has("k1") and "k1" in reloaded
    assert reloaded.get("k1") == {"status": "OK"}


def test_resume_after_simulated_crash(tmp_path):
    path = tmp_path / "checkpoint.jsonl"
    checkpoint = Checkpoint(path)
    checkpoint.put("k1", {"n": 1})
    checkpoint.flush()
    # Simulate a crash: a torn tail line that never parsed.
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"key": "k2", "result": {"n":')

    resumed = Checkpoint(path)
    assert resumed.load() == {"k1": {"n": 1}}
    resumed.put("k2", {"n": 2})
    resumed.flush()
    assert Checkpoint(path).load() == {"k1": {"n": 1}, "k2": {"n": 2}}


def test_duplicate_key_last_write_wins(tmp_path):
    path = tmp_path / "checkpoint.jsonl"
    checkpoint = Checkpoint(path)
    checkpoint.put("k1", {"n": 1})
    checkpoint.flush()
    checkpoint.put("k1", {"n": 2})
    checkpoint.flush()
    assert Checkpoint(path).load()["k1"] == {"n": 2}


def test_alias_table_hash_change_invalidates(tmp_path):
    path = tmp_path / "checkpoint.jsonl"
    old_key = make_key("email_001", "h", alias_table_hash="alias_v1", learned_alias_hash="l", schema_version="3.0")
    new_key = make_key("email_001", "h", alias_table_hash="alias_v2", learned_alias_hash="l", schema_version="3.0")
    checkpoint = Checkpoint(path)
    checkpoint.put(old_key, {"cached": True})
    checkpoint.flush()
    assert Checkpoint(path).has(old_key)
    assert not Checkpoint(path).has(new_key)


def test_learned_alias_hash_change_invalidates(tmp_path):
    old_key = make_key("email_001", "h", alias_table_hash="a", learned_alias_hash="learned_v1", schema_version="3.0")
    new_key = make_key("email_001", "h", alias_table_hash="a", learned_alias_hash="learned_v2", schema_version="3.0")
    checkpoint = Checkpoint(tmp_path / "c.jsonl")
    checkpoint.put(old_key, {"cached": True})
    checkpoint.flush()
    assert not Checkpoint(tmp_path / "c.jsonl").has(new_key)


def test_learned_alias_hash_frozen_under_scored_run(monkeypatch, tmp_path):
    import importlib

    learned = tmp_path / "alias_learned.jsonl"
    learned.write_text('{"label": "X"}\n', encoding="utf-8")
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SCORED_RUN", "0")
    importlib.reload(state)
    assert state.learned_alias_hash() != empty_hash()

    monkeypatch.setenv("SCORED_RUN", "1")
    importlib.reload(state)
    assert state.learned_alias_hash() == empty_hash()
    importlib.reload(state)


def test_run_resume_is_byte_identical(tmp_path):
    client = _client(tmp_path)
    first = state.checkpoint_path()
    checkpoint = tmp_path / "checkpoint.jsonl"

    from app import run as run_module

    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    run_module.run(data_dir=client.source, out_path=out_a, checkpoint_path=checkpoint)
    run_module.run(data_dir=client.source, out_path=out_b, checkpoint_path=checkpoint)
    assert out_a.read_bytes() == out_b.read_bytes()


def test_stale_pipeline_version_is_reprocessed(tmp_path):
    client = _client(tmp_path)
    checkpoint = tmp_path / "checkpoint.jsonl"
    from app import run as run_module

    out = tmp_path / "out.json"
    run_module.run(data_dir=client.source, out_path=out, checkpoint_path=checkpoint)

    lines = checkpoint.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    stale = json.loads(lines[0])
    stale["meta"]["pipeline"] = "ancient"
    checkpoint.write_text(json.dumps(stale) + "\n", encoding="utf-8")

    from app.checkpoint import make_key

    email = client.emails()[0]
    key = make_key("email_001", attachment_bytes_hash([client.read_bytes("attachments/email_001_SI.txt")]))
    assert run_module._cached_record(run_module.Checkpoint(checkpoint), key) is None
