#!/usr/bin/env python3
"""Stage-1 calibration: record the frozen LLM cache (plan 01 C6).

Runs the classifier over the inbox, calls the GLM fallback for any email the
rules/similarity layers do not resolve, and writes ``state/llm_cache.json``.
The cache is committed as a submission artifact and replayed under
``SCORED_RUN=1`` — after this tool has run, no network call is needed.

    KENARI_API_KEY=... python tools/calibrate_stage1.py --data data_v2

The tool is a no-op on the network when every email is already resolved (the
current rules resolve 100%), so it is safe to re-run offline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import llm_client, stage1_classify, state  # noqa: E402
from app.loader_client import DEFAULT_DATA_DIR, LoaderClient  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record the frozen Stage-1 LLM cache")
    parser.add_argument("--data", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--out", default=None, help="cache path (default state/llm_cache.json)")
    parser.add_argument("--live", action="store_true", help="force live calls where needed")
    args = parser.parse_args(argv)

    client = LoaderClient(args.data)
    cache_path = Path(args.out) if args.out else state.llm_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # The classifier itself consults the LLM only for the emails the rules and
    # the similarity layer leave unresolved, and caches every reply — so one
    # pass over the inbox records exactly the cache the frozen run replays.
    layers: dict[str, int] = {}
    before = len(llm_client.load_cache(cache_path))
    for email in client.emails():
        result = stage1_classify.classify(email)
        layer = result["_stage1"]["layer"]
        layers[layer] = layers.get(layer, 0) + 1

    cache = llm_client.load_cache(cache_path)
    llm_client.save_cache(cache, cache_path)
    print(f"layer mix:                 {layers}")
    print(f"LLM calls this run:        {len(cache) - before}")
    print(f"cache entries total:       {len(cache)}")
    print(f"cache written to:          {cache_path}")
    if not cache:
        print("note: rules+similarity resolve every email; the cache is empty and replay-safe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
