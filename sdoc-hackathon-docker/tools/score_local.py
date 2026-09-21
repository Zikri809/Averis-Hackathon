#!/usr/bin/env python3
"""Thin wrapper over ``server/scoring.py`` (plan 06) — never reimplements scoring.

    python tools/score_local.py submission.json
    python tools/score_local.py --run --data data_v2            # run then score
    python tools/score_local.py submission.json --stage1        # stage-1 detail
    python tools/score_local.py submission.json --json          # machine-readable

Exit codes: ``0`` scored, ``2`` cannot evaluate. The tool never decides whether
a score is good enough — the wave gates do (see ``ci.sh``).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.loader_client import DEFAULT_DATA_DIR, LoaderClient  # noqa: E402


def load_scoring():
    """Import the organizers' ``server/scoring.py`` without a package install."""
    path = PROJECT_DIR / "server" / "scoring.py"
    spec = importlib.util.spec_from_file_location("sdoc_scoring", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["sdoc_scoring"] = module
    spec.loader.exec_module(module)
    return module


def score(submission: dict, data_dir: Path) -> dict:
    truth_path = data_dir / "ground_truth.json"
    if not truth_path.is_file():
        raise FileNotFoundError(f"ground truth not found at {truth_path}")
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    return load_scoring().score_all(truth, submission)


def format_report(board: dict, stage1_only: bool = False) -> str:
    lines = []
    stage1 = board["stage1"]
    lines.append(
        f"stage1  macro_f1={stage1['macro_f1']:.4f}  accuracy={stage1['accuracy']:.4f}  "
        f"rule_pct={stage1['rule_pct'] if stage1['rule_pct'] is None else round(stage1['rule_pct'], 4)}"
    )
    if stage1_only:
        return "\n".join(lines)
    stage3 = board["stage3"]
    lines.append(
        f"stage3  defect_f1={stage3['defect_f1']:.4f}  exact_match={stage3['exact_match_rate']:.4f}  "
        f"docs={stage3['doc_total']}"
    )
    reliability = board["reliability"]
    lines.append(
        f"review  escalation_recall={reliability['escalation_recall']:.4f}  "
        f"precision={reliability['escalation_precision']:.4f}"
    )
    e2e = board["end_to_end"]
    lines.append(f"e2e     {e2e['success']}/{e2e['total']}  rate={e2e['rate']:.4f}")
    lines.append(f"FINAL   {board['final_score']:.6f}   (n_emails={board['n_emails']})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local scorer (wraps server/scoring.py)")
    parser.add_argument("submission", nargs="?", help="submission.json")
    parser.add_argument("--data", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--run", action="store_true", help="run app.run first (no file needed)")
    parser.add_argument("--out", default=None, help="where --run writes (default: no file)")
    parser.add_argument("--stage1", action="store_true", help="stage-1 report only")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    data_dir = Path(args.data)
    try:
        if args.run:
            from app import run as run_module

            submission = run_module.run(
                data_dir=data_dir,
                out_path=Path(args.out) if args.out else None,
                use_checkpoint=False,
            )
        elif args.submission:
            submission = json.loads(Path(args.submission).read_text(encoding="utf-8"))
        else:
            parser.error("pass submission.json or --run")
            return 2
        board = score(submission, data_dir)
    except Exception as exc:
        print(f"FAIL  cannot score: {exc}")
        return 2

    if args.json:
        print(json.dumps(board, indent=2, default=str))
    else:
        print(format_report(board, stage1_only=args.stage1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
