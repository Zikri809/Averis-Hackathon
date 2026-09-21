"""Runtime state: paths, the frozen-run flag, and submission safety (plan 00, F5).

Exports (documented contract):

* ``SCORED_RUN`` — ``True`` when ``SCORED_RUN=1``. The frozen run is
  deterministic and offline; extensions must never be imported under it.
* ``DATA_DIR`` / ``STATE_DIR`` / ``OUTBOX_DIR`` — resolved from the
  environment with repo-local defaults.
* ``assert_520(sub, email_ids=None)`` — raises before any write when the
  submission is not a complete, contract-valid 520-key payload.
* ``llm_cache_path()`` — frozen LLM cache location (plan 01 C6).
* ``alias_table_hash()`` / ``learned_alias_hash()`` — the two alias hashes
  that enter the checkpoint key (plan 00 F4, plan 05 G5).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .schema import SCHEMA_VERSION, validate_submission_record  # noqa: F401  (re-export)

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


#: ``SCORED_RUN=1`` freezes the pipeline (no LLM fallback, no learned aliases,
#: no OCR, no draft email). Read once at import; tests reload the module.
SCORED_RUN: bool = os.environ.get("SCORED_RUN", "0") == "1"

DATA_DIR: Path = _env_path("DATA_DIR", PROJECT_DIR / "data_v2")
STATE_DIR: Path = _env_path("STATE_DIR", PROJECT_DIR / "state")
OUTBOX_DIR: Path = _env_path("OUTBOX_DIR", PROJECT_DIR / "outbox")

CHECKPOINT_FILENAME = "checkpoint.jsonl"
SUBMISSION_FILENAME = "submission.json"
LLM_CACHE_FILENAME = "llm_cache.json"
ALIAS_LEARNED_FILENAME = "alias_learned.jsonl"
ALIAS_PROPOSALS_FILENAME = "alias_proposals.jsonl"

_alias_hash_cache: str | None = None


def ensure_dirs() -> None:
    """Create ``STATE_DIR``/``OUTBOX_DIR`` on demand (never at import time)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)


def checkpoint_path() -> Path:
    return STATE_DIR / CHECKPOINT_FILENAME


def submission_path() -> Path:
    return STATE_DIR / SUBMISSION_FILENAME


def llm_cache_path() -> Path:
    return STATE_DIR / LLM_CACHE_FILENAME


def alias_learned_path() -> Path:
    return STATE_DIR / ALIAS_LEARNED_FILENAME


def alias_proposals_path() -> Path:
    return STATE_DIR / ALIAS_PROPOSALS_FILENAME


def alias_table_hash() -> str:
    """Hash of the Text agent's alias table, or the empty hash before it lands.

    Plan 02 publishes ``app.stage2.aliases.ALIAS_TABLE_HASH``; this resolver
    keeps W0 self-contained and invalidates checkpoints the moment the real
    table appears (or changes).
    """
    global _alias_hash_cache
    if _alias_hash_cache is not None:
        return _alias_hash_cache
    try:  # pragma: no cover - exercised once plan 02 lands
        from .stage2.aliases import ALIAS_TABLE_HASH  # type: ignore
    except Exception:
        ALIAS_TABLE_HASH = hashlib.sha256(b"").hexdigest()
    _alias_hash_cache = ALIAS_TABLE_HASH
    return ALIAS_TABLE_HASH


def learned_alias_hash() -> str:
    """Hash of the learned-alias JSONL; empty hash when absent or frozen (G5)."""
    if SCORED_RUN:
        return hashlib.sha256(b"").hexdigest()
    path = alias_learned_path()
    try:
        payload = path.read_bytes()
    except OSError:
        payload = b""
    return hashlib.sha256(payload).hexdigest()


def refresh_hashes() -> None:
    """Recompute the module-level hash constants (call after an alias change)."""
    global ALIAS_TABLE_HASH, LEARNED_ALIAS_HASH, _alias_hash_cache
    _alias_hash_cache = None
    ALIAS_TABLE_HASH = alias_table_hash()
    LEARNED_ALIAS_HASH = learned_alias_hash()


#: Exported module-level hashes (DoD: ``SCHEMA_VERSION``, ``ALIAS_TABLE_HASH``,
#: ``LEARNED_ALIAS_HASH`` are importable constants). Refresh after an alias
#: change with :func:`refresh_hashes`.
ALIAS_TABLE_HASH: str = alias_table_hash()
LEARNED_ALIAS_HASH: str = learned_alias_hash()


def assert_520(submission: dict, email_ids=None) -> bool:
    """Raise ``AssertionError`` unless ``submission`` is a valid 520-key payload.

    Checks, in order: exactly 520 keys; the key set equals the inbox ids (when
    given); every record satisfies the submission contract. Returns ``True`` so
    callers can use it as a guard before writing.
    """
    if not isinstance(submission, dict):
        raise AssertionError(f"submission must be a dict, got {type(submission).__name__}")
    if len(submission) != 520:
        raise AssertionError(f"submission must have exactly 520 keys, got {len(submission)}")
    if email_ids is not None:
        expected = set(email_ids)
        actual = set(submission)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise AssertionError(
                f"submission keys must match the inbox ids "
                f"(missing={missing[:5]}{'…' if len(missing) > 5 else ''}, "
                f"extra={extra[:5]}{'…' if len(extra) > 5 else ''})"
            )
    errors: list[str] = []
    for email_id, record in submission.items():
        for problem in validate_submission_record(record):
            errors.append(f"{email_id}: {problem}")
        if len(errors) >= 10:
            break
    if errors:
        raise AssertionError("submission contract violations:\n  " + "\n  ".join(errors))
    return True
