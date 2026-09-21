# SDOC Demo Script (plan 07 O5)

> Six beats, ~10 minutes. Every step has a recorded fallback.
> **Rules:** no live SMTP, never set `REVEAL_GT`, never read `ground_truth.json`
> during the demo, keep the app on 8001 (8080 is the inbox service).

## Before the demo (T-10 min)

```bash
cd sdoc-hackathon-docker
docker compose -f docker-compose.yml -f docker-compose.app.yml up -d --build
python tools/preflight.py state/submission.json --data data_v2 \
    --server http://localhost:8080 --dry-run
```

Checklist:

- [ ] `GET http://localhost:8001/health` -> `"inbox": {"reachable": true, "emails": 520}`
- [ ] `GET http://localhost:8080/health` -> `scoring_available: true`
- [ ] Frozen submission present at `state/submission.json`
- [ ] Dashboard opens at <http://localhost:8001/ui>
- [ ] Browser zoom set so the diff table is legible from the back of the room

**Recorded fallbacks:** screenshot of the dashboard, screen recording of each
beat, and `state/submission.json` on disk. If anything live fails, switch to the
recording and keep talking — never debug on stage.

---

## Step 1 — Live triage with `decided_by` (1.5 min)

**Do:** open <http://localhost:8001/ui>, press **Run pipeline**.

> The app serves `POST /run` from the mounted `/data` (seconds) while
> `/health` still proves the inbox service is reachable — an HTTP-source run
> is byte-identical but takes ~8 min against the single-worker inbox, so the
> mount is the demo path and HTTP is the submit path.

**Say:** "520 emails in, 520 records out. Classification resolves 85.6% at the
rules layer with zero LLM calls; the remainder is TF-IDF similarity plus a
frozen cache."

```bash
docker compose -f docker-compose.yml -f docker-compose.app.yml \
  exec -T app python -c "import json;d=json.load(open('/state/submission.json'));\
from collections import Counter;print(Counter((v['category']) for v in d.values()))"
```

**Fallback:** pre-rendered screenshot of the summary table; the counts above
read from the committed frozen submission.

---

## Step 2 — A real two-field case (2 min)

**Do:** show `email_313` — a `pdf + pdf` pair with `container_count` **and**
`gross_weight_kg` defective (the v3-A6 replacement for the broken v2 example).

```bash
docker compose -f docker-compose.yml -f docker-compose.app.yml \
  exec -T app python -m app.run --data /data --out /tmp/one.json >/dev/null
docker compose -f docker-compose.yml -f docker-compose.app.yml \
  exec -T app python -c "import json;d=json.load(open('/state/submission.json'));\
print(json.dumps(d['email_313'],indent=1))"
```

**Say:** "The SI says 3 containers, the BL says 2; the weights differ too. The
verdict is the *complete* set — end-to-end scoring is exact-set, so a partial
answer scores zero for that email."

**Fallback:** `email_031` (`txt`, same two fields) or `email_097` (`xlsx + docx`).

---

## Step 3 — Negative control: the fallback declines (2 min)

**Do:** show a real `NET WEIGHT` line (5 files in the dataset) and the extractor
refusing to map it.

```bash
grep -rl "NET WEIGHT" data_v2/attachments | head -5
grep -h "NET WEIGHT" data_v2/attachments/*.txt | head -3
```

**Say:** "`NET WEIGHT` looks like a weight label, but it is not one of the seven
compared fields. The alias table is exact-match only — no substring matching —
so the extractor declines it rather than guessing. That refusal is what keeps
`gross_weight_kg` clean on every clean pair."

**Fallback:** recorded clip; the grep output above is static and can be shown
from the terminal history.

> **Do not** demo a fabricated "unseen label". `POL` and `Load Port` are already
> in the alias table, and `Loading Port`/`Origin Port` occur zero times in the
> data.

---

## Step 4 — Review a NEEDS_REVIEW case (2 min)

**Do:** open the review queue in the dashboard and resolve a pre-seeded case.

```bash
curl -s localhost:8001/review | python -m json.tool | head -30
```

**Say:** "These are the cases the pipeline refuses to guess: five impostor
documents, five missing attachments, five unreadable scans, five blank-field
SIs, plus the binary pairs the text-only parsers decline. Escalation recall
is 100% — it never calls an undecidable case clean."

```bash
curl -s localhost:8001/review/resolve -X POST -H "Content-Type: application/json" \
  -d '{"action":"confirm-escalation","email_id":"email_506"}'
```

**Fallback:** the 20 edge cases are fixed and known (`email_501`–`email_520`);
narrate them from the submission if the network drops. The queue holds those
20 items live; the resolve call above is also covered by
`tests/test_server.py::test_resolve_confirms_an_escalation`.

---

## Step 5 — Draft clarification email (1.5 min)

**Do:** show a drafted `.eml` with the banner.

```bash
curl -s localhost:8001/outbox | python -m json.tool
curl -s localhost:8001/outbox/email_313.eml | head -20
```

**Say:** "Draft only. There is no SMTP client anywhere in this repository — the
draft lands in a host-mounted outbox with a `DRAFT — NOT SENT` banner and waits
for a human."

**Fallback:** list `outbox/` in the file manager; the banner is in the file.

---

## Step 6 — Frozen run and submission (2 min)

**Do:** run the frozen pipeline and submit.

```bash
docker compose -f docker-compose.yml -f docker-compose.app.yml \
  exec -T -e SCORED_RUN=1 app python -m app.run --data /data --out /state/submission.json

python tools/preflight.py state/submission.json --data data_v2 \
  --server http://localhost:8080
```

**Say:** "`SCORED_RUN=1` disables the LLM fallback, learned aliases and OCR, so
this run is deterministic and offline. Preflight asserts 520 keys and every
record invariant before anything is sent, then submits and checks the returned
`n_emails`."

**Fallback:** pre-captured scoreboard JSON.

---

## Recovery commands

| Symptom | Action |
|---|---|
| App container unhealthy | `docker compose -f docker-compose.yml -f docker-compose.app.yml restart app` |
| Inbox service down | `docker compose up -d` (from `sdoc-hackathon-docker/`) |
| Port 8080 taken | change the `ports:` mapping in `docker-compose.yml` |
| Port 8001 taken | `APP_PORT=8002 docker compose ... up -d` |
| Run looks stale | delete `state/checkpoint.jsonl` and re-run |
| Network dies at step 3 or 5 | switch to the recorded clip |

## After the demo

```bash
docker compose -f docker-compose.yml -f docker-compose.app.yml down
```

Leave `state/` and `outbox/` in place — they are the evidence trail.
