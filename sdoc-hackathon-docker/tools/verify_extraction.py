#!/usr/bin/env python3
"""Structural oracle: agreement structure vs ground truth (plan 06 §1).

Ground truth reveals **which** fields differ, never the values. So this tool
checks the *structure* of extraction:

* ``has_defect=false`` -> all 7 SI/BL pairs equal after compare-normalization;
* ``defect_fields=[f]`` -> exactly ``f`` differs, all others equal;
* ``NEEDS_REVIEW/<reason>`` -> the expected exit.

    python tools/verify_extraction.py --data data_v2 --scope txt
    python tools/verify_extraction.py --data data_v2 --scope all

Exit non-zero on any structural mismatch. ``--scope txt`` evaluates the
``.txt`` pairs only (W2); the default evaluates everything (W3+).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import run as run_module  # noqa: E402
from app.loader_client import LoaderClient  # noqa: E402
from app.normalize import norm_compare  # noqa: E402
from app.schema import COMPARE_FIELDS  # noqa: E402
from app.stage2 import router  # noqa: E402
from app.stage2.aliases import ALIASES, ALIAS_TABLE_HASH  # noqa: E402
from app.stage2.txt_parser import parse_text  # noqa: E402


def register_parsers() -> None:
    """Register the parsers available at this wave."""
    if ".txt" not in router.registered_extensions():
        router.register(
            ".txt",
            lambda _path, data, _client: parse_text(data.decode("utf-8", errors="replace"), "txt"),
        )
    try:
        from app.stage2.binary_parsers import register_all

        register_all(router)
    except Exception:
        pass


def compare_field(si_value, bl_value, field_name: str) -> bool:
    """Structural equality after comparison normalization (plan 04 semantics)."""
    if si_value is None or bl_value is None:
        return si_value is bl_value
    if field_name in ("container_count", "gross_weight_kg"):
        return float(si_value) == float(bl_value)
    if field_name in ("port_of_loading", "port_of_discharge"):
        # Compare the name part only; never the LOCODE (v3-A5).
        from app.stage2.txt_parser import split_port

        si_name, _ = split_port(str(si_value))
        bl_name, _ = split_port(str(bl_value))
        return norm_compare(si_name) == norm_compare(bl_name)
    return norm_compare(si_value) == norm_compare(bl_value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SDOC structural extraction oracle")
    parser.add_argument("--data", required=True)
    parser.add_argument("--scope", choices=("txt", "all"), default="all")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    register_parsers()
    data_dir = Path(args.data)
    client = LoaderClient(data_dir)
    ground_truth = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))

    failures: list[str] = []
    checked = 0
    for email in client.emails():
        email_id = email["email_id"]
        truth = ground_truth.get(email_id)
        if truth is None:
            continue
        attachments = list(email.get("attachments") or [])
        if args.scope == "txt" and not all(str(a).endswith(".txt") for a in attachments):
            continue
        if truth["category"] != "BL_COMPARISON":
            continue
        # The oracle checks extracted *pairs*; zero/SI-only attachment cases
        # are gate behaviour, covered by verify_edges (plan 06 §2).
        if len(attachments) != 2:
            continue
        checked += 1

        category, _decided_by = run_module.classify_email(email)
        if category != "BL_COMPARISON":
            failures.append(f"{email_id}: classified {category}, expected BL_COMPARISON")
            continue

        extraction = run_module.extract_email(email, category, client)
        expected_reason = truth.get("review_reason")
        if truth["status"] == "NEEDS_REVIEW":
            if extraction.review_reason != expected_reason:
                failures.append(
                    f"{email_id}: exit {extraction.review_reason!r}, expected {expected_reason!r}"
                )
            continue

        if extraction.doc_status != "READY":
            failures.append(
                f"{email_id}: {extraction.review_reason!r}, expected a clean comparison"
            )
            continue

        si_doc, bl_doc = extraction.si_doc, extraction.bl_doc
        differing = [
            field_name
            for field_name in COMPARE_FIELDS
            if not compare_field(si_doc.fields[field_name], bl_doc.fields[field_name], field_name)
        ]
        expected = sorted(truth["defect_fields"])
        if sorted(differing) != expected:
            failures.append(f"{email_id}: differing={sorted(differing)}, expected={expected}")

    print(f"checked {checked} BL_COMPARISON emails (scope={args.scope})")
    print(f"ALIAS_TABLE_HASH={ALIAS_TABLE_HASH} ({len(ALIASES)} aliases)")
    if failures:
        print(f"FAIL  {len(failures)} structural mismatch(es):")
        for failure in failures[:40]:
            print(f"  {failure}")
        if len(failures) > 40:
            print(f"  … {len(failures) - 40} more")
        return 1
    print("ok    agreement structure matches ground truth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
