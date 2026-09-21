"""Append-only JSONL checkpoint with idempotent resume (plan 00, F4).

Key format (Foundation contract — extensions must not change it):

    sha256(email_id + attachment-bytes-hash + ALIAS_TABLE_HASH
           + LEARNED_ALIAS_HASH + SCHEMA_VERSION)

A change in any component invalidates the stored entry, so a re-run re-parses
instead of replaying stale data. ``load()`` folds the file in append order, so
the last write for a key wins; a crash mid-line is tolerated (the partial tail
is ignored).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from . import state
from .normalize import empty_hash

#: Checkpoint records wrap the pipeline payload under this key.
PAYLOAD_KEY = "result"


def attachment_bytes_hash(payloads: Iterable[bytes]) -> str:
    """Deterministic hash of an email's attachment bytes (order-independent)."""
    digest = hashlib.sha256()
    for blob in sorted(bytes(p) for p in payloads):
        digest.update(len(blob).to_bytes(8, "big"))
        digest.update(blob)
    return digest.hexdigest()


def make_key(
    email_id: str,
    attachment_hash: str = "",
    alias_table_hash: str | None = None,
    learned_alias_hash: str | None = None,
    schema_version: str | None = None,
) -> str:
    """Build the checkpoint key exactly as specified in plan 00 F4."""
    parts = [
        str(email_id),
        attachment_hash or empty_hash(),
        alias_table_hash if alias_table_hash is not None else state.alias_table_hash(),
        learned_alias_hash if learned_alias_hash is not None else state.learned_alias_hash(),
        schema_version if schema_version is not None else state.SCHEMA_VERSION,
    ]
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


class Checkpoint:
    """Append-only JSONL store; safe to kill and resume at any point."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else state.checkpoint_path()
        self._folded: dict[str, dict[str, Any]] | None = None
        self._pending: list[str] = []

    # -- reading ---------------------------------------------------------
    def _fold(self) -> dict[str, dict[str, Any]]:
        """Fold the JSONL into ``{key: record}``; ignores a torn final line."""
        if self._folded is not None:
            return self._folded
        records: dict[str, dict[str, Any]] = {}
        if self.path.is_file():
            with self.path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # torn tail from a crash — resume replays it
                    if not isinstance(record, dict) or "key" not in record:
                        continue
                    records[str(record["key"])] = record
        self._folded = records
        return records

    def load(self) -> dict[str, Any]:
        """Fold the JSONL into ``{key: payload}`` (last write wins)."""
        return {key: record.get(PAYLOAD_KEY) for key, record in self._fold().items()}

    def get(self, key: str, default: Any = None) -> Any:
        return self.load().get(key, default)

    def get_entry(self, key: str) -> dict[str, Any] | None:
        """Full record (payload + meta) for ``key``, or ``None``."""
        return self._fold().get(key)

    def has(self, key: str) -> bool:
        return key in self.load()

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    def __len__(self) -> int:
        return len(self.load())

    # -- writing ---------------------------------------------------------
    def put(self, key: str, result: Any, **meta: Any) -> None:
        """Stage an entry; call :meth:`flush` to make it durable."""
        record: dict[str, Any] = {"key": key, PAYLOAD_KEY: result}
        if meta:
            record["meta"] = meta
        self._pending.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        self._fold()[key] = record

    def flush(self) -> None:
        """Append pending entries and fsync, so a kill cannot lose them.

        A crash can leave a torn line without a trailing newline; appending a
        newline first keeps that torn line unparseable (and therefore ignored)
        instead of fusing it with the next record.
        """
        if not self._pending:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            if self.path.stat().st_size:
                with self.path.open("rb") as probe:
                    probe.seek(-1, os.SEEK_END)
                    if probe.read(1) != b"\n":
                        handle.write(b"\n")
            for line in self._pending:
                handle.write(line.encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._pending.clear()

    def close(self) -> None:
        self.flush()

    def __enter__(self) -> "Checkpoint":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def load(path: str | Path | None = None) -> dict[str, Any]:
    """Convenience: read a checkpoint file into a ``{key: payload}`` dict."""
    return Checkpoint(path).load()
