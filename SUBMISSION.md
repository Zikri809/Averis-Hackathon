# Submission Evidence Log (plan 07 O6)

> Frozen-run checklist, commands, outputs, and artifact hashes.
> Update the score and hash blocks after each frozen run.

## Frozen-run checklist

| # | Check | Command | Status |
|---|---|---|---|
| 1 | App + inbox healthy | `docker compose -f docker-compose.yml -f docker-compose.app.yml ps` | ✅ |
| 2 | Inbox reachable from the app | `GET http://localhost:8001/health` -> `inbox.reachable: true` | ✅ |
| 3 | Frozen run (offline) | `exec -e SCORED_RUN=1 app python -m app.run --data /data --out /state/submission.json` | ✅ |
| 4 | 520-key assert + invariants | `python tools/preflight.py state/submission.json --data data_v2` | ✅ |
| 5 | Dry-run baseline | `python tools/preflight.py ... --server http://localhost:8080 --dry-run` | ✅ |
| 6 | Real submit -> `n_emails == 520` | `python tools/preflight.py ... --server http://localhost:8080` | ✅ |
| 7 | Restart resume identical | `docker compose restart app` then re-run, compare JSON | ✅ |
| 8 | `REVEAL_GT` unset everywhere | `tests/test_compose_config.py` | ✅ |
| 9 | No SMTP anywhere | `tests/test_no_smtp.py` (plan 05) | ⏳ plan 05 |
| 10 | No ground-truth route | `tests/test_server.py::test_no_ground_truth_route_exists` | ✅ |

## Commands and outputs

### Environment

```text
$ docker compose -f docker-compose.yml -f docker-compose.app.yml ps
SERVICE   STATUS                   PORTS
app       Up (healthy)             0.0.0.0:8001->8001/tcp
inbox     Up (healthy)             0.0.0.0:8080->8000/tcp

$ curl -s localhost:8001/health
{"status":"ok","app_port":8001,"scored_run":false,
 "inbox":{"reachable":true,"status":"ok","emails":520,"scoring_available":true},
 "submission_present":true}
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

### Preflight and submit

```text
$ python tools/preflight.py state/submission.json --data data_v2 --server http://localhost:8080 --dry-run
ok    read 520 records from state/submission.json
ok    /health ok (520 emails, scoring available)
ok    520 keys, ids match inbox, every record satisfies the submission contract
ok    all records carry the exact required keys
info  categories=BL_COMPARISON, GENERAL, INVOICE_QUERY, SI_REQUEST, SPAM
info  review_reasons=None, missing_attachment, missing_value, unreadable
ok    dry-run baseline final_score=0.0124 (expected ~0.0124)
ok    submitted: n_emails=520 final_score=0.3
```

### Restart resume

```text
$ docker compose ... exec -T app python -m app.run --data /data --out /state/submission_a.json
wrote 520 records to /state/submission_a.json
$ docker compose ... restart app
$ docker compose ... exec -T app python -m app.run --data /data --out /state/submission_b.json
wrote 520 records to /state/submission_b.json
$ python -c "compare a and b"
restart resume identical: True 520
checkpoint lines: 1040   # unchanged by further runs -> resume is idempotent
```

### Local score report

```text
$ python tools/score_local.py state/submission.json
stage1  macro_f1=1.0000  accuracy=1.0000  rule_pct=0.8558
stage3  defect_f1=0.0000  exact_match=0.7700  docs=200
review  escalation_recall=1.0000  precision=0.4444
e2e     0/46  rate=0.0000
FINAL   0.300000   (n_emails=520)
```

> `stage3`/`e2e` are 0 because **plan 04 (`stage3_compare.py`) is not landed**.
> The extraction structure is correct (51/51 txt OK pairs clean, 33/33 txt
> defects structurally exact — see `tools/verify_extraction.py --scope txt`);
> only the comparison stage is missing. W2's e2e >= 0.70 gate opens when plan 04
> merges.

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
| `state/submission.json` | _run the snippet_ | |
| `state/checkpoint.jsonl` | _run the snippet_ | |
| `state/llm_cache.json` | _run the snippet_ | |

Committed constants:

| Constant | Value |
|---|---|
| `SCHEMA_VERSION` | `3.0` |
| `ALIAS_TABLE_HASH` | `8051184827f032e348387e6c9d25ddfd1b521fb36af6aef7efa910883d05a018` |
| `LEARNED_ALIAS_HASH` (scored run) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (empty hash) |
| `PIPELINE_VERSION` | `w0` |

## Score log

| Run | Date | stage1 | stage3 | e2e | final | Notes |
|---|---|---|---|---|---|---|
| Baseline (all GENERAL) | 2026-09-21 | 0.0414 | 0.0000 | 0/46 | 0.0124 | dry-run pipe proof |
| W1 (classification live) | 2026-09-21 | 1.0000 | 0.0000 | 0/46 | 0.3000 | rules + sim + frozen cache |
| W2 (text extraction) | 2026-09-21 | 1.0000 | 0.0000 | 0/46 | 0.3000 | awaits plan 04 comparison |
| W3 (binary extraction) | _pending_ | | | | | awaits plans 03 + 04 |
| W5 (frozen) | _pending_ | | | | | |

## Known gaps at this commit

| Gap | Owner | Effect |
|---|---|---|
| `email_501`–`505` exit `missing_value` not `wrong_doc_type` | plan 03 (`doctype.py`) | 5 escalation reasons wrong; e2e unaffected |
| 25 binary pairs exit `unreadable` | plan 03 (W2 router stub) | 13 binary defects + 12 OK pairs uncompared |
| No comparison stage -> every pair `OK` | plan 04 (`stage3_compare.py`) | e2e 0/46; stage3 F1 0.0 |
| Review queue / alias learning / draft email / fallback | plan 05 | extensions default-off; app returns empty projections |
| `/ui` is static with no resolution form wired | plan 05 X5 | display-only for now |
