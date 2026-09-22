"""Draft-only clarification emails for mismatches (plan 05 X4)."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .. import state

BOOKING_RX = re.compile(r"\bBooking(?:\s+(?:Ref(?:erence)?|No\.?))?\s*[:#-]\s*([A-Z0-9][A-Z0-9./_-]+)", re.I)


def is_enabled() -> bool:
    if state.SCORED_RUN:
        return False
    return os.environ.get("ENABLE_DRAFT_EMAIL", "1") in ("1", "true", "True")


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


def render_body_template(email: dict, diff_report: dict[str, dict], booking_ref: str | None = None) -> str:
    """Deterministic template-based email body (always available offline)."""
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


def render_body(
    email: dict,
    diff_report: dict[str, dict],
    booking_ref: str | None = None,
    *,
    use_ai: bool = True,
) -> str:
    """Render draft clarification email body with AI, falling back to template."""
    if use_ai and not state.SCORED_RUN:
        try:
            from .. import llm_client

            ai_text = llm_client.draft_clarification_email(email, diff_report, booking_ref)
            if ai_text:
                ai_lines = ["DRAFT — NOT SENT", "", ai_text.strip()]
                if booking_ref and f"Booking Ref: {booking_ref}" not in ai_text:
                    ai_lines.extend(["", f"Booking Ref: {booking_ref}"])
                ai_lines.extend(["", "DRAFT — NOT SENT"])
                return "\n".join(ai_lines)
        except Exception:
            pass
    return render_body_template(email, diff_report, booking_ref)


def build_message(
    email: dict,
    diff_report: dict[str, dict],
    booking_ref: str | None = None,
    *,
    use_ai: bool = True,
) -> str:
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
    ref = booking_ref or booking_ref_from_evidence(diff_report)
    body = render_body(email, diff_report, ref, use_ai=use_ai)
    return "\n".join(headers) + "\n\n" + body + "\n"


def write_draft(
    email: dict,
    diff_report: dict[str, dict],
    outbox_dir: str | Path | None = None,
    *,
    use_ai: bool = True,
) -> Path:
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
    msg = build_message(email, diff_report, use_ai=use_ai)
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


def draft_from_verdict(
    email: dict,
    verdict: Any,
    outbox_dir: str | Path | None = None,
    *,
    use_ai: bool = True,
) -> Path:
    if not getattr(verdict, "has_defect", False):
        raise ValueError("drafts require a mismatch verdict")
    payload = {**email, "status": "MISMATCH"}
    return write_draft(payload, getattr(verdict, "diff_report", {}), outbox_dir, use_ai=use_ai)


def generate_drafts(
    submission: dict[str, dict],
    client: Any = None,
    outbox_dir: str | Path | None = None,
    *,
    use_ai: bool = True,
    max_ai: int = 5,
) -> list[Path]:
    """Generate drafts for MISMATCH records.

    Prioritizes key demo emails (e.g. email_313, email_097).
    Limits AI calls to `max_ai` to ensure fast completion and falls back to template.
    """
    if state.SCORED_RUN:
        return []
    if client is None:
        from ..loader_client import LoaderClient

        source = str(state.DATA_DIR)
        try:
            client = LoaderClient(source)
        except Exception:
            return []

    try:
        from ..stage2 import router
        from ..stage2.binary_parsers import register_all

        register_all(router)
    except Exception:
        pass

    from ..run import compare_pair, extract_email

    mismatches = [
        eid
        for eid, r in sorted(submission.items())
        if isinstance(r, dict) and r.get("status") == "MISMATCH"
    ]
    demo_prio = ["email_313", "email_097", "email_031", "email_004"]
    mismatches = [eid for eid in demo_prio if eid in mismatches] + [
        eid for eid in mismatches if eid not in demo_prio
    ]

    generated: list[Path] = []
    ai_count = 0

    for eid in mismatches:
        try:
            email_data = client.get(eid)
            cat = submission[eid].get("category", "BL_COMPARISON")
            ext = extract_email(email_data, cat, client)
            if not ext.ready or not ext.has_docs:
                continue
            verdict = compare_pair(ext)
            if verdict is None or not verdict.has_defect:
                continue

            allow_ai = use_ai and (ai_count < max_ai)
            path = draft_from_verdict(email_data, verdict, outbox_dir, use_ai=allow_ai)
            generated.append(path)
            if allow_ai:
                ai_count += 1
        except Exception:
            continue

    return generated


def run_hook(submission: dict[str, dict]) -> None:
    """Extension runner hook wired into run_extensions."""
    if not is_enabled():
        return
    generate_drafts(submission)
