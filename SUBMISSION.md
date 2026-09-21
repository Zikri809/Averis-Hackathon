# Submission Evidence Log (plan 07 O6)

> Frozen-run checklist, commands, outputs, and artifact hashes.
> Measured 2026-09-21 after plans 00–06 merged (issues #1–#7 closed).
> Update the score and hash blocks after each frozen run.

## Frozen-run checklist

| # | Check | Command | Status |
|---|---|---|---|
| 1 | App + inbox healthy | `GET http://localhost:8001/health` + `GET http://localhost:8000/health` | ✅ both `ok` (see below) |
| 2 | Inbox reachable from the app | `GET http://localhost:8001/health` -> `inbox.reachable: true, emails: 520` | ✅ |
| 3 | Frozen run (deterministic) | `SCORED_RUN=1 python -m app.run --data data_v2 --out state/submission.json --no-checkpoint` | ✅ 520 records |
| 4 | 520-key assert + invariants | `python tools/preflight.py state/submission.json --data data_v2` | ✅ offline green |
| 5 | Dry-run baseline | `python tools/preflight.py ... --server http://localhost:8000 --dry-run` | ✅ `final_score=0.0124` |
| 6 | Real submit -> `n_emails == 520` | `python tools/preflight.py ... --server http://localhost:8000` | ✅ `final_score=0.825784` |
| 7 | Restart resume identical | `tests/test_run_stub.py::test_checkpoint_makes_second_run_identical` | ✅ suite green |
| 8 | `REVEAL_GT` unset everywhere | `tests/test_compose_config.py::test_app_never_enables_reveal_gt` | ✅ |
| 9 | No SMTP anywhere | `tests/test_no_smtp.py` | ✅ 265 passed |
| 10 | No ground-truth route | `tests/test_server.py::test_no_ground_truth_route_exists` | ✅ |
| 11 | HTTP-source run == mount-source run | byte-compare `httpsrc.json` vs `submission.json` | ✅ identical |
| 12 | Full suite green | `python -m pytest` in `sdoc-hackathon-docker/` | ✅ 265 passed |

> Note on #1: verified 2026-09-21 via real compose stack —
> `docker compose -f docker-compose.yml -f docker-compose.app.yml up -d --build`
> builds both images (app adds `openpyxl`, `python-docx`, `pymupdf`) and both
> containers report healthy: inbox `0.0.0.0:8080->8000`, app
> `0.0.0.0:8001->8001`. Compose wiring is additionally pinned by
> `tests/test_compose_config.py` (8 tests: inbox `8080:8000`, app
> `${APP_PORT:-8001}:8001`, `INBOX_URL=http://inbox:8000`, host-mounted
> `./state` + `./outbox`, no `REVEAL_GT`).

## Commands and outputs

### Environment

```text
$ docker compose -f docker-compose.yml -f docker-compose.app.yml ps
NAME                          SERVICE   STATUS                    PORTS
sdoc-hackathon-docker-app-1   app       Up (healthy)              0.0.0.0:8001->8001/tcp
sdoc-hackathon-docker-inbox-1 inbox     Up (healthy)              0.0.0.0:8080->8000/tcp

$ curl -s localhost:8080/health
{"status":"ok","emails":520,"scoring_available":true}

$ curl -s localhost:8001/health
{"status":"ok","app_port":8001,"scored_run":false,
 "inbox":{"reachable":true,"status":"ok","emails":520,"scoring_available":true},
 "submission_present":true}

$ curl -s -X POST localhost:8001/run
{"status":"ok","n_records":520,"out":".../state/submission.json"}

$ curl -s localhost:8001/review | python -c "import json,sys; print(len(json.load(sys.stdin)['items']))"
45
```

### Frozen run

```text
$ docker compose ... exec -T -e SCORED_RUN=1 app python -m app.run --data /data --out /state/submission.json
wrote 520 records to /state/submission.json
SCHEMA_VERSION=3.0
ALIAS_TABLE_HASH=8051184827f032e348387e6c9d25ddfd1b521fb36af6aef7efa910883d05a018
LEARNED_ALIAS_HASH=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
SCORED_RUN=1
```

> Stale-checkpoint incident (2026-09-21, fixed): the first in-container run
> replayed 38/520 stale records from the host-mounted `state/checkpoint.jsonl`
> (written pre-stage-3, same `PIPELINE_VERSION=w0`, so the version gate waved
> them through — 33 txt MISMATCHes flipped to OK, 5 edges mis-reasoned).
> Fix: `PIPELINE_VERSION` bumped `w0` → `w5` (`app/run.py`; bump on ANY
> behaviour change). Re-run recomputed everything fresh and matches the
> independently computed local frozen artifact byte-for-byte in content.

Submission mix: `OK` 442, `MISMATCH` 33,
`NEEDS_REVIEW` 45 (`unreadable` 30, `wrong_doc_type` 5,
`missing_attachment` 5, `missing_value` 5).

### Preflight and submit

```text
$ python tools/preflight.py state/submission.json --data data_v2
ok    read 520 records from state/submission.json
ok    520 keys, ids match inbox, every record satisfies the submission contract
ok    all records carry the exact required keys
info  categories=BL_COMPARISON, GENERAL, INVOICE_QUERY, SI_REQUEST, SPAM
info  review_reasons=None, missing_attachment, missing_value, unreadable, wrong_doc_type
ok    offline checks green (steps 1-3); pass --server for steps 4-6

$ python tools/preflight.py state/submission.json --data data_v2 --server http://localhost:8000 --dry-run
ok    read 520 records from state/submission.json
ok    /health ok (520 emails, scoring available)
ok    520 keys, ids match inbox, every record satisfies the submission contract
ok    all records carry the exact required keys
info  categories=BL_COMPARISON, GENERAL, INVOICE_QUERY, SI_REQUEST, SPAM | review_reasons=None, ...
ok    dry-run baseline final_score=0.0124 (expected ~0.0124)
ok    submitted: n_emails=520 final_score=0.8257842597688497
```

### Restart resume

```text
$ docker compose ... exec -T -e SCORED_RUN=1 app python -m app.run --data /data --out /state/submission.json
wrote 520 records ... SCORED_RUN=1
$ # content sha256 of parsed submission: 7d72b3a1...984e1edf
$ docker compose -f docker-compose.yml -f docker-compose.app.yml restart app
app-1 Restarting ... Started
$ curl -s localhost:8001/health  # ok, inbox reachable, submission_present: true
$ docker compose ... exec -T -e SCORED_RUN=1 app python -m app.run --data /data --out /state/submission.json
wrote 520 records ... SCORED_RUN=1
$ # content sha256 of parsed submission: 7d72b3a1...984e1edf  -> identical: True
```

Host-mounted `./state` + `./outbox` survive the restart; the checkpoint resume
is byte-identical in content. Also covered in-suite by
`tests/test_run_stub.py::test_checkpoint_makes_second_run_identical`.

### Source-independence

```text
$ SCORED_RUN=1 python -m app.run --data http://localhost:8000 --out httpsrc.json --no-checkpoint
$ python -c "compare submission.json and httpsrc.json"
mount-source run == http-source run: True (520 keys, byte-identical)
```

> The HTTP-source run takes ~8 min against the single-worker inbox
> (per-attachment round trips in the organizers' harness, which we consume
> as-is). `POST /run` therefore serves the `/data` mount when it is present
> (`app/server.py::_data_source`) and keeps `INBOX_URL` for liveness —
> identical bytes, demo-usable latency. Pinned by
> `tests/test_server.py::test_run_prefers_the_mounted_dataset_over_http`.

### Local score report

```text
$ python tools/score_local.py state/submission.json
stage1  macro_f1=1.0000  accuracy=1.0000  rule_pct=0.8558
stage3  defect_f1=0.8354  exact_match=0.9350  docs=200
review  escalation_recall=1.0000  precision=0.4444
e2e     33/46  rate=0.7174
FINAL   0.825784   (n_emails=520)
```

> This is the ARCHITECTURE §5 Tier-0 ceiling ("txt core alone ≈ 0.83"):
> all 33 txt defects are exact-set correct; the 13 binary-pair defects
> escalate `unreadable` (no `binary_parsers` module — plan 03 follow-up).
> Escalation recall is 1.0: nothing undecidable is called clean.

## Artifact hashes

Recompute after every frozen run:

```bash
python - <<'PY'
import hashlib, json, pathlib
root = pathlib.Path("sdoc-hackathon-docker")
for rel in ("state/submission.json", "state/checkpoint.jsonl", "state/llm_cache.json"):
    path = root / rel
    if path.is_file():
        print(f"{rel:28} sha256={hashlib.sha256(path.read_bytes()).hexdigest()} bytes={path.stat().st_size}")
PY
```

| Artifact | sha256 | Bytes |
|---|---|---|
| `state/submission.json` (frozen in-container, 2026-09-21) | `035e303c7b1747390acb3ffcaa68769598a1031325137c0615ce592939e54f27` | 93261 |
| content sha256 of parsed submission (line-ending independent) | `7d72b3a1f128c73b2b2393e6072da4b599000b1aaf9eff3129fcd93b984e1edf` | — |
| `state/checkpoint.jsonl` | _run the snippet_ | |
| `state/llm_cache.json` | committed (plan 01 C6; trailing-newline deterministic via `llm_client.save_cache`) | |

Committed constants:

| Constant | Value |
|---|---|
| `SCHEMA_VERSION` | `3.0` |
| `ALIAS_TABLE_HASH` | `8051184827f032e348387e6c9d25ddfd1b521fb36af6aef7efa910883d05a018` |
| `LEARNED_ALIAS_HASH` (scored run) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (empty hash) |
| `PIPELINE_VERSION` | `w5` (bumped from `w0` when plans 00–06 all landed; gate for stale checkpoints) |

## Score log

| Run | Date | stage1 | stage3 | e2e | final | Notes |
|---|---|---|---|---|---|---|
| Baseline (all GENERAL) | 2026-09-21 | 0.0414 | 0.0000 | 0/46 | 0.0124 | dry-run pipe proof |
| W1 (classification live) | 2026-09-21 | 1.0000 | 0.0000 | 0/46 | 0.3000 | rules + sim + frozen cache |
| W2 (text extraction) | 2026-09-21 | 1.0000 | 0.0000 | 0/46 | 0.3000 | awaited plan 04 comparison |
| W4 (stage3 landed) | 2026-09-21 | 1.0000 | 0.8354 | 33/46 | 0.8258 | txt exact; binaries escalate |
| W5 (frozen, SCORED_RUN=1) | 2026-09-21 | 1.0000 | 0.8354 | 33/46 | 0.8258 | live submit `n_emails=520` |

## Known gaps at this commit

| Gap | Owner | Effect |
|---|---|---|
| 25 binary pairs exit `unreadable` (no `binary_parsers` module; router W2 stub) | plan 03 follow-up (`stage2/binary_parsers.py`) | 13 binary defects uncompared; e2e 33/46 instead of 46/46; −0.1742 vs perfect |
| e2e gate ≥ 0.95 (plan 07 DoD) | blocked on the row above | current e2e 0.7174; everything Ops-owned is done |
| Live guards (`/ground_truth`, `/secrets`, `/gt` on both services) | verified 2026-09-21 | all six return 404; `REVEAL_GT` appears only in comments |
