"""Draft-only clarification emails for mismatches (plan 05 X4)."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .. import state

BOOKING_RX = re.compile(r"\bBooking(?:\s+(?:Ref(?:erence)?|No\.?))?\s*[:#-]\s*([A-Z0-9][A-Z0-9./_-]+)", re.I)


def is_enabled() -> bool:
    return (not state.SCORED_RUN) and os.environ.get("ENABLE_DRAFT_EMAIL") == "1"


def booking_ref_from_evidence(diff_report: dict[str, dict] | None) -> str | None:
    if not diff_report:
        return None
    for entry in diff_report.values():
        if not isinstance(entry, dict):
            continue
        for key in ("si_raw", "bl_raw", "si_value", "bl_value"):
            match = BOOKING_RX.search(str(entry.get(key) or ""))
            if match:
                return match.group(1)
    return None


def _recipient(email: dict) -> str:
    return str(email.get("from") or email.get("From") or "").strip()


def _subject(email: dict) -> str:
    subject = str(email.get("subject") or email.get("Subject") or "Shipping document clarification")
    return f"DRAFT - clarification needed: {subject}"


def render_body(email: dict, diff_report: dict[str, dict], booking_ref: str | None = None) -> str:
    lines = [
        "DRAFT — NOT SENT",
        "",
        "Hello,",
        "",
        "We found the following SI/BL mismatch(es) during document verification:",
        "",
    ]
    for field, entry in sorted(diff_report.items()):
        if not isinstance(entry, dict) or entry.get("outcome") == "equal":
            continue
        lines.append(f"- {field}: SI={entry.get('si_value')!r}; BL={entry.get('bl_value')!r}")
    if booking_ref:
        lines.extend(["", f"Booking Ref: {booking_ref}"])
    lines.extend(
        [
            "",
            "Please review and advise the correct draft details.",
            "",
            "DRAFT — NOT SENT",
        ]
    )
    return "\n".join(lines)


def build_message(email: dict, diff_report: dict[str, dict], booking_ref: str | None = None) -> str:
    if state.SCORED_RUN:
        raise RuntimeError("draft emails are disabled for scored runs")
    recipient = _recipient(email)
    if not recipient:
        raise ValueError("source email has no From recipient")
    headers = [
        f"To: {recipient}",
        "From: draft-outbox@localhost",
        f"Subject: {_subject(email)}",
        "X-SDOC-Draft: DRAFT — NOT SENT",
        "Content-Type: text/plain; charset=utf-8",
    ]
    body = render_body(email, diff_report, booking_ref or booking_ref_from_evidence(diff_report))
    return "\n".join(headers) + "\n\n" + body + "\n"


def write_draft(email: dict, diff_report: dict[str, dict], outbox_dir: str | Path | None = None) -> Path:
    if state.SCORED_RUN:
        raise RuntimeError("draft emails are disabled for scored runs")
    status = email.get("status")
    if status is not None and status != "MISMATCH":
        raise ValueError("drafts are only allowed for MISMATCH cases")
    if email.get("review_reason") is not None:
        raise ValueError("drafts are forbidden for NEEDS_REVIEW cases")
    outbox = Path(outbox_dir) if outbox_dir is not None else state.OUTBOX_DIR
    outbox.mkdir(parents=True, exist_ok=True)
    email_id = str(email.get("email_id") or "draft")
    target = outbox / f"{email_id}.eml"
    msg = build_message(email, diff_report)
    tmp_path = target.with_name(target.name + f".{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as tmp:
            tmp.write(msg)
        os.replace(tmp_path, target)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
    return target


def draft_from_verdict(email: dict, verdict: Any, outbox_dir: str | Path | None = None) -> Path:
    if not getattr(verdict, "has_defect", False):
        raise ValueError("drafts require a mismatch verdict")
    payload = {**email, "status": "MISMATCH"}
    return write_draft(payload, getattr(verdict, "diff_report", {}), outbox_dir)
