#!/usr/bin/env python3
"""Submission preflight (plan 06 §3, run before every submit).

Steps 1–3 are offline and always run; steps 4–6 (dry-run submit, real submit,
compose restart) need the organizers' Docker server and only run when
``--server`` is given.

    python tools/preflight.py submission.json
    python tools/preflight.py submission.json --server http://localhost:8080

Exit codes: ``0`` green, ``1`` contract failure, ``2`` cannot evaluate.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schema import (  # noqa: E402
    CATEGORIES,
    REVIEW_REASONS,
    SUBMISSION_KEYS,
    validate_submission_record,
)
from app.state import assert_520  # noqa: E402

SAMPLE_BASELINE = 0.0124
BASELINE_TOLERANCE = 0.002


def _fail(message: str) -> None:
    print(f"FAIL  {message}")


def _ok(message: str) -> None:
    print(f"ok    {message}")


def _http_json(url: str, payload: dict | None = None, timeout: float = 30.0) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def load_submission(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def check_structure(submission: dict, inbox_ids: set[str] | None) -> list[str]:
    """Step 2 + 3: key completeness and per-record contract."""
    errors: list[str] = []
    if not isinstance(submission, dict):
        return [f"submission must be a JSON object, got {type(submission).__name__}"]
    if len(submission) != 520:
        errors.append(f"expected 520 keys, found {len(submission)}")
    if inbox_ids is not None:
        missing = sorted(inbox_ids - set(submission))
        extra = sorted(set(submission) - inbox_ids)
        if missing:
            errors.append(f"missing {len(missing)} email ids (e.g. {missing[:3]})")
        if extra:
            errors.append(f"{len(extra)} unexpected keys (e.g. {extra[:3]})")
    for email_id, record in list(submission.items())[:520]:
        for problem in validate_submission_record(record):
            errors.append(f"{email_id}: {problem}")
        if len(errors) > 20:
            errors.append("… more violations suppressed")
            break
    return errors


def _inbox_ids_from_data(data_dir: str | Path) -> set[str] | None:
    inbox = Path(data_dir) / "inbox"
    if not inbox.is_dir():
        return None
    return {path.stem for path in inbox.glob("email_*.json")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SDOC submission preflight")
    parser.add_argument("submission", help="path to submission.json")
    parser.add_argument("--data", default=None, help="dataset dir (for inbox id comparison)")
    parser.add_argument("--server", default=None, help="organizers' inbox base URL")
    parser.add_argument("--dry-run", action="store_true", help="POST sample_submission (needs --server)")
    args = parser.parse_args(argv)

    try:
        submission = load_submission(args.submission)
    except Exception as exc:
        _fail(f"cannot read {args.submission}: {exc}")
        return 2

    data_dir = Path(args.data) if args.data else Path(__file__).resolve().parent.parent / "data_v2"
    inbox_ids = _inbox_ids_from_data(data_dir)
    if inbox_ids is None:
        _fail(f"no inbox/ under {data_dir}; pass --data")
        return 2

    _ok(f"read {len(submission)} records from {args.submission}")

    if args.server:
        try:
            health = _http_json(args.server.rstrip("/") + "/health")
        except Exception as exc:
            _fail(f"GET /health failed: {exc}")
            return 2
        if health.get("emails") != 520:
            _fail(f"/health reports {health.get('emails')} emails, expected 520")
            return 1
        if not health.get("scoring_available"):
            _fail("/health scoring_available=false — /secrets mount missing, do not submit")
            return 1
        _ok(f"/health ok ({health.get('emails')} emails, scoring available)")

    errors = check_structure(submission, inbox_ids)
    if errors:
        for problem in errors:
            _fail(problem)
        return 1
    _ok("520 keys, ids match inbox, every record satisfies the submission contract")

    missing_keys = [k for record in submission.values() for k in SUBMISSION_KEYS if k not in record]
    if missing_keys:
        _fail(f"{len(missing_keys)} records miss required keys")
        return 1
    _ok("all records carry the exact required keys")
    print(
        "info  categories="
        + ", ".join(sorted({str(r.get('category')) for r in submission.values()}))
        + " | review_reasons="
        + ", ".join(sorted({str(r.get('review_reason')) for r in submission.values()}))
    )

    if not args.server:
        _ok("offline checks green (steps 1–3); pass --server for steps 4–6")
        return 0

    if args.dry_run:
        try:
            sample = _http_json(args.server.rstrip("/") + "/sample_submission")
            scoreboard = _http_json(args.server.rstrip("/") + "/submit", sample)
        except Exception as exc:
            _fail(f"dry-run POST /submit failed: {exc}")
            return 2
        if scoreboard.get("n_emails") != 520:
            _fail(f"dry-run n_emails={scoreboard.get('n_emails')}, expected 520")
            return 1
        final = float(scoreboard.get("final_score", -1))
        if abs(final - SAMPLE_BASELINE) > BASELINE_TOLERANCE:
            _fail(f"dry-run final_score={final}, expected ~{SAMPLE_BASELINE}")
            return 1
        _ok(f"dry-run baseline final_score={final:.4f} (expected ~{SAMPLE_BASELINE})")

    try:
        scoreboard = _http_json(args.server.rstrip("/") + "/submit", submission)
    except Exception as exc:
        _fail(f"POST /submit failed: {exc}")
        return 2
    if scoreboard.get("n_emails") != 520:
        _fail(f"n_emails={scoreboard.get('n_emails')}, expected 520 — do not believe final_score")
        return 1
    _ok(f"submitted: n_emails=520 final_score={scoreboard.get('final_score')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
