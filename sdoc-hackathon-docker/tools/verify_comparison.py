#!/usr/bin/env python3
"""Comparison verifier: local score report + per-email diagnosis (plan 06 §1/§5).

Wraps ``server/scoring.py`` (never reimplements it) and adds the per-email
breakdown the stage plans need: which emails lost end-to-end credit and why.

    python tools/verify_comparison.py --data data_v2 submission.json
    python tools/verify_comparison.py --data data_v2 --run --scope txt

``--scope txt`` reports only emails whose attachments are all ``.txt`` (W2);
the default reports everything (W3+).

Exit codes: ``0`` report produced, ``1`` a scope failure, ``2`` cannot evaluate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.loader_client import LoaderClient  # noqa: E402
from tools.score_local import format_report, load_scoring  # noqa: E402

#: Wave thresholds from ARCHITECTURE §5 / plan 06.
WAVE_THRESHOLDS = {
    "w1": {"stage1_macro_f1": 0.95},
    "w2": {"end_to_end_rate": 0.70},
    "w3": {"end_to_end_rate": 0.95, "stage3_defect_f1": 0.95},
}


def _fail(message: str) -> None:
    print(f"FAIL  {message}")


def diagnose(truth: dict, submission: dict, scope_ids: set[str] | None) -> list[str]:
    """Per-email end-to-end misses, with the reason."""
    lines: list[str] = []
    for email_id, record in sorted(truth.items()):
        if scope_ids is not None and email_id not in scope_ids:
            continue
        if not (record["category"] == "BL_COMPARISON" and record.get("has_defect")):
            continue
        got = submission.get(email_id, {})
        if got.get("category") != "BL_COMPARISON":
            lines.append(f"{email_id}: not routed (category={got.get('category')!r})")
            continue
        if not got.get("has_defect"):
            lines.append(f"{email_id}: defect missed (status={got.get('status')!r})")
            continue
        got_fields = set(got.get("defect_fields") or [])
        want_fields = set(record["defect_fields"])
        if got_fields != want_fields:
            lines.append(
                f"{email_id}: fields {sorted(got_fields)} != {sorted(want_fields)}"
            )
    return lines


def scope_ids_for(data_dir: Path, scope: str) -> set[str] | None:
    if scope == "all":
        return None
    client = LoaderClient(data_dir)
    ids = set()
    for email in client.emails():
        attachments = list(email.get("attachments") or [])
        if attachments and all(str(a).endswith(".txt") for a in attachments):
            ids.add(email["email_id"])
    return ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SDOC comparison verifier")
    parser.add_argument("submission", nargs="?", help="submission.json")
    parser.add_argument("--data", required=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--scope", choices=("txt", "all"), default="all")
    parser.add_argument("--wave", choices=tuple(WAVE_THRESHOLDS), default=None,
                        help="enforce that wave's thresholds")
    parser.add_argument("--diagnose", action="store_true", help="list per-email misses")
    args = parser.parse_args(argv)

    data_dir = Path(args.data)
    try:
        if args.run:
            from app import run as run_module

            submission = run_module.run(data_dir=data_dir, out_path=None, use_checkpoint=False)
        elif args.submission:
            submission = json.loads(Path(args.submission).read_text(encoding="utf-8"))
        else:
            parser.error("pass submission.json or --run")
            return 2
        truth = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
        board = load_scoring().score_all(truth, submission)
    except Exception as exc:
        _fail(f"cannot evaluate: {exc}")
        return 2

    print(format_report(board))

    failures: list[str] = []
    if args.wave:
        thresholds = WAVE_THRESHOLDS[args.wave]
        if "stage1_macro_f1" in thresholds:
            got = board["stage1"]["macro_f1"]
            print(f"{args.wave}: stage1.macro_f1={got:.4f} (need {thresholds['stage1_macro_f1']})")
            if got < thresholds["stage1_macro_f1"]:
                failures.append(f"{args.wave}: stage1 macro_f1 {got:.4f} below gate")
        if "end_to_end_rate" in thresholds:
            got = board["end_to_end"]["rate"]
            print(f"{args.wave}: end_to_end.rate={got:.4f} (need {thresholds['end_to_end_rate']})")
            if got < thresholds["end_to_end_rate"]:
                failures.append(f"{args.wave}: e2e {got:.4f} below gate")
        if "stage3_defect_f1" in thresholds:
            got = board["stage3"]["defect_f1"]
            print(f"{args.wave}: stage3.defect_f1={got:.4f} (need {thresholds['stage3_defect_f1']})")
            if got < thresholds["stage3_defect_f1"]:
                failures.append(f"{args.wave}: stage3 defect_f1 {got:.4f} below gate")

    if args.diagnose:
        misses = diagnose(truth, submission, scope_ids_for(data_dir, args.scope))
        if misses:
            print(f"\nend-to-end misses ({len(misses)}):")
            for line in misses[:60]:
                print(f"  {line}")
            if len(misses) > 60:
                print(f"  … {len(misses) - 60} more")

    if failures:
        for failure in failures:
            _fail(failure)
        return 1
    print("ok    report produced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
