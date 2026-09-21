#!/usr/bin/env python3
"""Edge-case verifier (plan 06 §2) — the 20 golden edges + the BL classes.

Checks a **submission** (not extraction) against the verified expectations:

* 501–505 ``NEEDS_REVIEW/wrong_doc_type``
* 506–510 ``NEEDS_REVIEW/missing_attachment``
* 511–515 ``NEEDS_REVIEW/unreadable``
* 516–520 ``NEEDS_REVIEW/missing_value``
* the 94 zero-attachment BLs are ``BL_COMPARISON`` and OK except 506/508/510
* the 23 INVOICE_QUERY bodies matching ``dropped|still missing`` stay
  non-escalated
* the 46 defect emails carry the exact ``defect_fields`` set
* the 13 binary defects are listed (diagnostic only until W3)

    python tools/verify_edges.py --data data_v2 submission.json

Exit non-zero on any failure. When ``submission.json`` is omitted the tool
runs ``app.run`` itself (useful at a wave gate).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.loader_client import LoaderClient  # noqa: E402
from app.schema import CATEGORIES  # noqa: E402

# ---------------------------------------------------------------------------
# golden expectations (plan 06 §2, verified against data_v2)
# ---------------------------------------------------------------------------
EDGE_EXPECTATIONS: dict[str, tuple[str, str]] = {}
for _n in range(501, 506):
    EDGE_EXPECTATIONS[f"email_{_n:03d}"] = ("NEEDS_REVIEW", "wrong_doc_type")
for _n in range(506, 511):
    EDGE_EXPECTATIONS[f"email_{_n:03d}"] = ("NEEDS_REVIEW", "missing_attachment")
for _n in range(511, 516):
    EDGE_EXPECTATIONS[f"email_{_n:03d}"] = ("NEEDS_REVIEW", "unreadable")
for _n in range(516, 521):
    EDGE_EXPECTATIONS[f"email_{_n:03d}"] = ("NEEDS_REVIEW", "missing_value")

#: §2a — per-field null expectations for 516–520, derived from the SI files
#: (NOT derivable from ground truth).
MISSING_VALUE_FIELDS: dict[str, set[str]] = {
    "email_516": {"gross_weight_kg"},
    "email_517": {"port_of_loading", "port_of_discharge"},
    "email_518": {"port_of_discharge", "gross_weight_kg"},
    "email_519": {"shipper", "container_count"},
    "email_520": {"consignee"},
}

#: The 46 defect emails and their exact field sets (plan 06 §2).
DEFECTS: dict[str, list[str]] = {
    "email_004": ["consignee", "notify_party"],
    "email_013": ["port_of_discharge"],
    "email_025": ["container_count", "port_of_discharge"],
    "email_031": ["container_count", "gross_weight_kg"],
    "email_043": ["container_count"],
    "email_046": ["notify_party"],
    "email_065": ["notify_party", "port_of_discharge"],
    "email_071": ["container_count", "port_of_discharge"],
    "email_091": ["container_count"],
    "email_097": ["container_count", "gross_weight_kg"],
    "email_107": ["consignee", "container_count"],
    "email_111": ["container_count"],
    "email_119": ["port_of_loading"],
    "email_121": ["gross_weight_kg"],
    "email_128": ["gross_weight_kg", "port_of_loading"],
    "email_129": ["port_of_discharge", "port_of_loading"],
    "email_133": ["gross_weight_kg"],
    "email_144": ["consignee", "container_count"],
    "email_145": ["shipper"],
    "email_174": ["notify_party", "port_of_discharge"],
    "email_178": ["container_count"],
    "email_182": ["container_count", "port_of_discharge"],
    "email_225": ["consignee"],
    "email_243": ["port_of_discharge", "port_of_loading"],
    "email_256": ["port_of_discharge", "shipper"],
    "email_270": ["port_of_discharge"],
    "email_291": ["consignee", "container_count"],
    "email_300": ["notify_party", "shipper"],
    "email_302": ["container_count"],
    "email_312": ["notify_party", "shipper"],
    "email_313": ["container_count", "gross_weight_kg"],
    "email_324": ["container_count", "shipper"],
    "email_334": ["consignee", "shipper"],
    "email_342": ["container_count", "notify_party"],
    "email_351": ["container_count", "gross_weight_kg"],
    "email_354": ["gross_weight_kg", "notify_party"],
    "email_361": ["gross_weight_kg", "port_of_discharge"],
    "email_379": ["shipper"],
    "email_410": ["port_of_loading"],
    "email_416": ["gross_weight_kg"],
    "email_426": ["container_count", "port_of_discharge"],
    "email_434": ["port_of_discharge"],
    "email_435": ["gross_weight_kg"],
    "email_468": ["container_count", "port_of_loading"],
    "email_481": ["consignee"],
    "email_499": ["gross_weight_kg"],
}

#: The 13 binary defect emails (plan 06 §2) — must be exact by the W3 gate.
BINARY_DEFECTS = {
    "email_097",
    "email_107",
    "email_243",
    "email_291",
    "email_300",
    "email_302",
    "email_313",
    "email_351",
    "email_354",
    "email_434",
    "email_435",
    "email_481",
    "email_499",
}

#: The 3 genuine zero-attachment escalations; the other 91 are OK.
ZERO_ATTACHMENT_REVIEW = {"email_506", "email_508", "email_510"}

PHRASE_RX = re.compile(r"dropped|still missing", re.IGNORECASE)


def _fail(message: str) -> None:
    print(f"FAIL  {message}")


def _ok(message: str) -> None:
    print(f"ok    {message}")


def check_edges(submission: dict, ground_truth: dict) -> list[str]:
    failures: list[str] = []
    for email_id, (status, reason) in sorted(EDGE_EXPECTATIONS.items()):
        record = submission.get(email_id)
        if record is None:
            failures.append(f"{email_id}: missing from the submission")
            continue
        if record.get("status") != status or record.get("review_reason") != reason:
            failures.append(
                f"{email_id}: {record.get('status')}/{record.get('review_reason')!r}, "
                f"expected {status}/{reason}"
            )
        if record.get("category") != "BL_COMPARISON":
            failures.append(f"{email_id}: category {record.get('category')!r}, expected BL_COMPARISON")
    return failures


def check_zero_attachment_bls(submission: dict, ground_truth: dict, emails: dict) -> list[str]:
    failures: list[str] = []
    zero_att = [
        email_id
        for email_id, email in emails.items()
        if ground_truth[email_id]["category"] == "BL_COMPARISON" and not email["attachments"]
    ]
    if len(zero_att) != 94:
        failures.append(f"expected 94 zero-attachment BL emails, found {len(zero_att)}")
    for email_id in zero_att:
        record = submission.get(email_id, {})
        if record.get("category") != "BL_COMPARISON":
            failures.append(f"{email_id}: category {record.get('category')!r}, expected BL_COMPARISON")
            continue
        if email_id in ZERO_ATTACHMENT_REVIEW:
            if record.get("review_reason") != "missing_attachment":
                failures.append(
                    f"{email_id}: {record.get('review_reason')!r}, expected missing_attachment"
                )
        elif record.get("status") != "OK":
            failures.append(f"{email_id}: status {record.get('status')!r}, expected OK")
    return failures


def check_phrase_negatives(submission: dict, ground_truth: dict, emails: dict) -> list[str]:
    """The 23 INVOICE_QUERY bodies matching the phrase must stay non-escalated."""
    failures: list[str] = []
    matches = [eid for eid, email in emails.items() if PHRASE_RX.search(email["body"])]
    if len(matches) != 28:
        failures.append(f"expected 28 phrase-matching emails, found {len(matches)}")
    invoice_matches = [eid for eid in matches if ground_truth[eid]["category"] == "INVOICE_QUERY"]
    if len(invoice_matches) != 23:
        failures.append(f"expected 23 INVOICE_QUERY phrase matches, found {len(invoice_matches)}")
    for email_id in invoice_matches:
        record = submission.get(email_id, {})
        if record.get("status") != "OK" or record.get("review_reason") is not None:
            failures.append(
                f"{email_id}: {record.get('status')}/{record.get('review_reason')!r}, "
                "expected OK/None (category gate must prevent escalation)"
            )
    return failures


def check_defects(submission: dict, scope: str) -> list[str]:
    """Exact defect_fields; binary emails only at W3 scope."""
    failures: list[str] = []
    for email_id, expected in sorted(DEFECTS.items()):
        if scope == "txt" and email_id in BINARY_DEFECTS:
            continue
        record = submission.get(email_id, {})
        got = sorted(record.get("defect_fields") or [])
        if record.get("status") != "MISMATCH" or got != expected:
            failures.append(
                f"{email_id}: {record.get('status')}/{got}, expected MISMATCH/{expected}"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SDOC edge-case verifier")
    parser.add_argument("submission", nargs="?", help="submission.json (runs app.run when omitted)")
    parser.add_argument("--data", required=True)
    parser.add_argument("--scope", choices=("txt", "all"), default="all")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    data_dir = Path(args.data)
    client = LoaderClient(data_dir)
    ground_truth = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    emails = {email["email_id"]: email for email in client.emails()}

    if args.submission:
        submission = json.loads(Path(args.submission).read_text(encoding="utf-8"))
    else:
        from app import run as run_module

        submission = run_module.run(data_dir=data_dir, out_path=None, use_checkpoint=False)

    failures: list[str] = []
    failures += check_edges(submission, ground_truth)
    failures += check_zero_attachment_bls(submission, ground_truth, emails)
    failures += check_phrase_negatives(submission, ground_truth, emails)
    failures += check_defects(submission, args.scope)

    if not args.quiet:
        print(f"scope={args.scope} emails={len(emails)} submission_keys={len(submission)}")
        print(f"edges checked: {len(EDGE_EXPECTATIONS)} | defects checked: "
              f"{len(DEFECTS) - (len(BINARY_DEFECTS) if args.scope == 'txt' else 0)}")
    if failures:
        print(f"FAIL  {len(failures)} edge failure(s):")
        for failure in failures[:40]:
            print(f"  {failure}")
        if len(failures) > 40:
            print(f"  … {len(failures) - 40} more")
        return 1
    _ok("all edges, zero-attachment classes, phrase negatives and defects exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
