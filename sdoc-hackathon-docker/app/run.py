"""Pipeline orchestrator (plan 00, F6).

W0 is a **plumbing gate**: the stages are resolved at runtime and every stage
that has not landed yet falls back to the default record (``GENERAL``/``OK``).
The run therefore always completes with exactly 520 results, whatever the
state of the tree, and the W0 submission scores the baseline (~0.0124).

Gate ordering is part of the contract (v3-A1):

1. classification decides the category;
2. only for ``BL_COMPARISON`` does the attachment rule run:
   ``0 attachments AND body =~ /dropped|still missing/i`` -> missing_attachment,
   ``exactly 1 attachment (SI only)`` -> missing_attachment,
   ``2 attachments`` -> parse.
   The 23 INVOICE_QUERY bodies that match the phrase never reach this gate.

Stage hooks (owned by other plans; resolved lazily, absent at W0):

===========================  =========================================  ==========
Hook                          Contract                                   Owner
===========================  =========================================  ==========
``app.stage1_classify.classify(email)``  -> ``{"category", "decided_by"}``  plan 01
``app.stage2.router.extract_pair(email, client)`` -> ``ExtractionResult``  plan 02
``app.stage3_compare.compare(si_doc, bl_doc)`` -> ``Verdict``          plan 04
``app.stage2.binary_parsers.register_all(router)``                     plan 03
===========================  =========================================  ==========

F7: extension hooks are imported **only when ``SCORED_RUN != 1``**.
"""
from __future__ import annotations

import argparse
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):  # ``python app/run.py`` support
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "app"

from . import state
from .checkpoint import Checkpoint, attachment_bytes_hash, make_key
from .loader_client import DEFAULT_DATA_DIR, LoaderClient
from .schema import (
    CATEGORIES,
    ExtractionResult,
    Verdict,
    default_submission_record,
    submission_record,
    validate_submission_record,
)

#: Bumped whenever pipeline behaviour changes, so a checkpoint written by an
#: older pipeline is ignored instead of replaying stale records. The checkpoint
#: *key* is unchanged (plan 00 F4); the version lives in the entry meta.
PIPELINE_VERSION = "w0"

#: v3-A1 — the only body phrase that escalates a zero-attachment BL request.
MISSING_PHRASE = re.compile(r"dropped|still missing", re.IGNORECASE)

#: Extension hook modules wired by :func:`load_extensions` (F7).
EXTENSION_MODULES = (
    "app.extensions.alias_learning",
    "app.extensions.review_queue",
    "app.extensions.llm_label_fallback",
    "app.extensions.draft_email",
)


# ---------------------------------------------------------------------------
# lazy stage resolution
# ---------------------------------------------------------------------------
def _load_attr(module_name: str, attr_name: str) -> Callable[..., Any] | None:
    """Import ``module_name`` and return ``attr_name`` when callable, else None."""
    import importlib

    try:
        module = importlib.import_module(module_name)
    except Exception:
        return None
    attr = getattr(module, attr_name, None)
    return attr if callable(attr) else None


def classify_email(email: dict) -> tuple[str, str | None]:
    """Stage 1 hook; W0 default is ``GENERAL`` for every email (baseline)."""
    classify = _load_attr("app.stage1_classify", "classify")
    if classify is not None:
        try:
            result = classify(email)
        except Exception:
            result = None
        if isinstance(result, dict) and result.get("category") in CATEGORIES:
            return str(result["category"]), result.get("decided_by")
        if isinstance(result, str) and result in CATEGORIES:
            return result, None
    return "GENERAL", None


def extract_email(email: dict, category: str, client: LoaderClient) -> ExtractionResult:
    """Stage 2 with the W0 gate ordering (v3-A1).

    Only ``BL_COMPARISON`` emails are ever parsed — the category gate runs
    *first*, which is what keeps the 23 INVOICE_QUERY phrase matches from
    escalating. Never raises: a stage-2 failure is a per-email ``unreadable``.
    """
    if category != "BL_COMPARISON":
        return ExtractionResult()

    attachments = list(email.get("attachments") or [])
    body = str(email.get("body") or "")

    if len(attachments) == 0:
        if MISSING_PHRASE.search(body):
            return ExtractionResult(doc_status="NEEDS_REVIEW", review_reason="missing_attachment")
        return ExtractionResult()
    if len(attachments) == 1:
        return ExtractionResult(doc_status="NEEDS_REVIEW", review_reason="missing_attachment")

    extract_pair = _load_attr("app.stage2.router", "extract_pair")
    if extract_pair is not None:
        try:
            result = extract_pair(email, client)
        except Exception:
            result = None
        if isinstance(result, ExtractionResult):
            return result

    return ExtractionResult(doc_status="NEEDS_REVIEW", review_reason="unreadable")


def compare_pair(extraction: ExtractionResult) -> Verdict | None:
    """Stage 3 hook; ``None`` means "no comparison module yet" (W0)."""
    compare = _load_attr("app.stage3_compare", "compare")
    if compare is None:
        return None
    return compare(extraction.si_doc, extraction.bl_doc)


# ---------------------------------------------------------------------------
# submission assembly
# ---------------------------------------------------------------------------
def build_record(
    category: str,
    extraction: ExtractionResult,
    verdict: Verdict | None,
    decided_by: str | None = None,
) -> dict:
    """Map one email's outcome onto the exact submission record."""
    if extraction.doc_status == "NEEDS_REVIEW":
        return submission_record(
            category=category,
            status="NEEDS_REVIEW",
            review_reason=extraction.review_reason,
            decided_by=decided_by,
        )
    if verdict is not None and verdict.has_defect:
        return submission_record(
            category=category,
            status="MISMATCH",
            defect_fields=verdict.defect_fields,
            has_defect=True,
            decided_by=decided_by,
        )
    return submission_record(category=category, decided_by=decided_by)


# ---------------------------------------------------------------------------
# extension wiring (F7)
# ---------------------------------------------------------------------------
def load_extensions() -> list[Any]:
    """Import extension hooks — **never** under ``SCORED_RUN=1`` (F7/G1)."""
    if state.SCORED_RUN:
        return []
    hooks: list[Any] = []
    for module_name in EXTENSION_MODULES:
        is_enabled = _load_attr(module_name, "is_enabled")
        if is_enabled is not None:
            hooks.append((module_name, is_enabled))
    return hooks


def run_extensions(hooks: list[Any], submission: dict) -> None:
    """Best-effort demo hooks; never allowed to break the frozen output."""
    for module_name, is_enabled in hooks:
        try:
            if is_enabled():
                pass
        except Exception:
            print(f"[extensions] {module_name} hook failed (ignored)", file=sys.stderr)


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def _cached_record(checkpoint: Checkpoint, key: str) -> dict | None:
    """Return a cached record only when it is valid and same-pipeline-version."""
    entry = checkpoint.get_entry(key)
    if not entry:
        return None
    if entry.get("meta", {}).get("pipeline") != PIPELINE_VERSION:
        return None
    record = entry.get("result")
    if isinstance(record, dict) and not validate_submission_record(record):
        return record
    return None


def run(
    data_dir: str | Path | None = None,
    out_path: str | Path | None = None,
    checkpoint_path: str | Path | None = None,
    use_checkpoint: bool = True,
) -> dict:
    """Run the pipeline over every email and return the 520-key submission."""
    state.ensure_dirs()
    client = LoaderClient(data_dir if data_dir is not None else DEFAULT_DATA_DIR)

    registrar = _load_attr("app.stage2.binary_parsers", "register_all")
    if registrar is not None:
        try:
            from .stage2 import router as router_module

            registrar(router_module)
        except Exception:
            print("[stage2] binary parser registration failed (ignored)", file=sys.stderr)

    checkpoint = (
        Checkpoint(checkpoint_path)
        if checkpoint_path is not None
        else (Checkpoint() if use_checkpoint else None)
    )

    submission: dict[str, dict] = {}
    for email in client.emails():
        email_id = str(email["email_id"])
        key: str | None = None
        try:
            category, decided_by = classify_email(email)
            attachments = list(email.get("attachments") or [])

            if checkpoint is not None:
                blobs: list[bytes] = []
                for att_path in attachments:
                    try:
                        blobs.append(client.read_bytes(att_path))
                    except Exception:
                        blobs.append(b"")
                key = make_key(email_id, attachment_bytes_hash(blobs))
                cached = _cached_record(checkpoint, key)
                if cached is not None:
                    submission[email_id] = cached
                    continue

            extraction = extract_email(email, category, client)
            verdict = compare_pair(extraction) if extraction.ready else None
            record = build_record(category, extraction, verdict, decided_by)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            record = default_submission_record()

        submission[email_id] = record
        if checkpoint is not None and key is not None:
            checkpoint.put(key, record, pipeline=PIPELINE_VERSION)
            checkpoint.flush()

    state.assert_520(submission, email_ids=client.email_ids())

    if out_path is not None:
        client.write_submission(submission, out_path)

    if not state.SCORED_RUN:
        run_extensions(load_extensions(), submission)

    return submission


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SDOC pipeline (plan 00 orchestrator)")
    parser.add_argument("--data", default=str(DEFAULT_DATA_DIR), help="dataset dir or HTTP URL")
    parser.add_argument("--out", default=str(state.submission_path()), help="submission JSON path")
    parser.add_argument("--no-checkpoint", action="store_true", help="ignore the checkpoint file")
    args = parser.parse_args(argv)

    submission = run(data_dir=args.data, out_path=args.out, use_checkpoint=not args.no_checkpoint)
    print(f"wrote {len(submission)} records to {args.out}")
    print(
        f"SCHEMA_VERSION={state.SCHEMA_VERSION} "
        f"ALIAS_TABLE_HASH={state.alias_table_hash()} "
        f"LEARNED_ALIAS_HASH={state.learned_alias_hash()} "
        f"SCORED_RUN={int(state.SCORED_RUN)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
