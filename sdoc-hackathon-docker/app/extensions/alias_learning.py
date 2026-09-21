"""Append-only learned aliases for the demo review flow (plan 05 X1).

The frozen parser's generated alias table always wins. Learned aliases live in
``state/`` and only fill gaps; they are never loaded on ``SCORED_RUN=1``.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Iterator

from .. import state
from ..normalize import compute_alias_table_hash, norm_label
from ..schema import COMPARE_FIELDS
from ..stage2.aliases import ALIASES, NON_COMPARE_ALIASES

LOCK_TIMEOUT_SECONDS = 5.0
POLL_SECONDS = 0.05


def is_enabled() -> bool:
    return (not state.SCORED_RUN) and os.environ.get("ENABLE_ALIAS_LEARNING") == "1"


@contextlib.contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Cross-platform advisory lock using atomic lock-file creation."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock {lock_path}")
            time.sleep(POLL_SECONDS)
    try:
        os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()


def _read_jsonl(path: Path) -> list[dict]:
    if state.SCORED_RUN or not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _atomic_append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(path):
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        payload = existing
        if payload and not payload.endswith("\n"):
            payload += "\n"
        payload += json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        tmp_path = path.with_name(path.name + f".{os.getpid()}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8", newline="\n") as tmp:
                tmp.write(payload)
            os.replace(tmp_path, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()


def _existing_aliases() -> dict[str, str]:
    aliases = dict(ALIASES)
    for row in _read_jsonl(state.alias_learned_path()):
        if not row.get("confirmed"):
            continue
        alias = norm_label(row.get("label") or row.get("alias"))
        field = row.get("field")
        if alias and field in COMPARE_FIELDS and alias not in aliases:
            aliases[alias] = str(field)
    return aliases


def validate(label: str, field: str, existing_aliases: dict[str, str] | None = None) -> tuple[bool, str]:
    """Validate a proposed learned alias per G4."""
    if state.SCORED_RUN:
        return False, "alias learning is disabled for scored runs"
    if field not in COMPARE_FIELDS:
        return False, f"unknown compared field: {field}"
    normalized = norm_label(label)
    if not normalized:
        return False, "label is blank after normalization"
    if normalized in NON_COMPARE_ALIASES:
        return False, f"{label!r} is a known non-field label"

    aliases = existing_aliases or _existing_aliases()
    owner = aliases.get(normalized)
    if owner is not None:
        if owner == field:
            return False, "alias already exists for this field"
        return False, f"alias collides with existing field {owner}"

    for alias, owner in aliases.items():
        if owner == field:
            continue
        if normalized in alias or alias in normalized:
            return False, f"alias overlaps existing alias for {owner}"
    return True, "ok"


def propose(label: str, field: str, reviewer: str | None = None, email_id: str | None = None) -> dict:
    ok, reason = validate(label, field)
    if not ok:
        raise ValueError(reason)
    row = {
        "ts": time.time(),
        "email_id": email_id,
        "reviewer": reviewer,
        "label": label,
        "normalized": norm_label(label),
        "field": field,
        "confirmed": False,
    }
    _atomic_append_jsonl(state.alias_proposals_path(), row)
    return row


def confirm(label: str, field: str, reviewer: str | None = None, email_id: str | None = None) -> dict:
    ok, reason = validate(label, field)
    if not ok:
        raise ValueError(reason)
    row = {
        "ts": time.time(),
        "email_id": email_id,
        "reviewer": reviewer,
        "label": label,
        "normalized": norm_label(label),
        "field": field,
        "confirmed": True,
    }
    _atomic_append_jsonl(state.alias_learned_path(), row)
    state.refresh_hashes()
    return row


def load() -> dict[str, str]:
    """Return confirmed learned aliases only, with generated aliases taking precedence."""
    if state.SCORED_RUN:
        return {}
    learned: dict[str, str] = {}
    aliases = dict(ALIASES)
    for row in _read_jsonl(state.alias_learned_path()):
        if not row.get("confirmed"):
            continue
        field = row.get("field")
        normalized = norm_label(row.get("label") or row.get("alias"))
        if field not in COMPARE_FIELDS or not normalized or normalized in aliases:
            continue
        ok, _reason = validate(normalized, str(field), {**aliases, **learned})
        if ok:
            learned[normalized] = str(field)
    return learned


def merged_aliases() -> dict[str, str]:
    return {**ALIASES, **load()}


def table_hash() -> str:
    return compute_alias_table_hash(load())


def resolve(payload: dict) -> dict:
    """Server action for confirm/correct/confirm-escalation."""
    action = str(payload.get("action") or "").strip()
    label = str(payload.get("label") or payload.get("raw_label") or "").strip()
    field = str(payload.get("field") or "").strip()
    reviewer = payload.get("reviewer")
    email_id = payload.get("email_id")
    if action == "correct":
        return {"status": "proposed", "entry": propose(label, field, reviewer, email_id)}
    if action == "confirm":
        return {"status": "confirmed", "entry": confirm(label, field, reviewer, email_id)}
    if action == "confirm-escalation":
        return {"status": "confirmed-escalation", "email_id": email_id}
    raise ValueError(f"unknown resolution action: {action}")
