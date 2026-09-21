# Plan 07 — Deployment, Demo & Submission (owner: Ops/Demo agent)

> Scope: the participant app container, wiring to the organizers' `inbox` service, the frozen-run
> submission, the demo script, and the submission checklist. **Consumes the organizers' harness;
> never re-declares or duplicates it.**

## Deliverable

One `docker compose` up that runs the pipeline against the organizers' `inbox` service, a review
dashboard, a frozen `submission.json`, and a rehearsed demo.

## Files owned

| File | Purpose |
|---|---|
| `sdoc-hackathon-docker/app/server.py` | Participant FastAPI app: `/run`, `/submission`, `/review`, `/outbox`, static UI |
| `sdoc-hackathon-docker/Dockerfile.app` | Participant image (adds `openpyxl`, `python-docx`, `pymupdf`) |
| `sdoc-hackathon-docker/docker-compose.app.yml` | Compose override that **attaches** to the existing `inbox` network |
| `outbox/` (host volume `./outbox`) | Draft `.eml` output; created at runtime, never committed |
| `DEMO.md` (repo root) | Timed demo script + fallbacks |
| `SUBMISSION.md` (repo root) | Final checklist and evidence log |
| `tests/test_server.py`, `tests/test_compose_config.py` | Endpoint smoke + compose guard |

## Verified harness facts (do not contradict)

| Fact | Value |
|---|---|
| Organizers' service | `inbox` (build `./server`), published **host 8080 → container 8000** |
| Inside compose network | `http://inbox:8000` |
| Endpoints | `GET /health`, `/emails`, `/emails/{id}`, `/attachments/{path}`, `/sample_submission`, `POST /submit` |
| `/submit` body | **flat dict, all 520 keys**; missing keys silently default to `GENERAL` (`scoring.py:46`) |
| Ground truth | `/secrets/ground_truth.json`, never served; `REVEAL_GT` must stay unset |
| Data | `./data_v2:/data:ro`; loader default `DATA_DIR=/data` |
| Deps missing from organizers' image | `openpyxl`, `python-docx`, `pymupdf` (add in participant image) |

## Tasks

| # | Task | Verification |
|---|---|---|
| O1 | `Dockerfile.app`: python:3.13-slim + fastapi/uvicorn + parser deps; copies `app/` | `docker build` succeeds; container `GET /health` on own port |
| O2 | `docker-compose.app.yml`: `app` service joins the shipped compose network; env `INBOX_URL=http://inbox:8000`, `DATA_DIR=/data`, `STATE_DIR=/state`, `OUTBOX_DIR=/outbox`, `SCORED_RUN=0`; volumes `./state:/state`, `./outbox:/outbox` | `docker compose -f docker-compose.yml -f docker-compose.app.yml up` → app reaches inbox `/health` |
| O3 | `app/server.py`: `POST /run` (orchestrates, writes `$STATE_DIR/submission.json`), `GET /submission`, `GET /review` (queue), `POST /review/resolve`, `GET /outbox`, static `/ui` | curl each endpoint; 520-key output |
| O4 | Frozen run: `SCORED_RUN=1 python -m app.run --data /data --out /state/submission.json` (container path, not `app/state/`) then `preflight` then `POST /submit` | `n_emails == 520`; score recorded |
| O5 | `DEMO.md`: 6-step script with timings and fallbacks (see below) | dry-run twice; every step has a recorded fallback |
| O6 | `SUBMISSION.md`: evidence log (commands, outputs, scores, hashes of submission + alias table + checkpoint) | reviewable |

## Demo script (corrected per `../ARCHITECTURE.md` §6)

| Step | Beat | Fallback |
|---|---|---|
| 1 | Triage view: category tags + `decided_by` per email (pre-rendered from a cached run; `--offline`) | static screenshot |
| 2 | Two-field case: `email_313` (pdf) or `email_097` (xlsx/docx) — side-by-side `diff_report` + confidence | `email_031` (txt) |
| 3 | **Negative control:** `NET WEIGHT` unmatched label correctly declined, threshold visible | recorded clip |
| 4 | Pre-seeded NEEDS_REVIEW case → resolve live → learned alias JSONL gains the entry | recorded clip |
| 5 | Draft `.eml` preview for a real MISMATCH — "DRAFT — NOT SENT" | file listing in `outbox/` |
| 6 | Frozen run → `/submit` → scoreboard after 520-key assert | pre-captured scoreboard JSON |

**Demo rules:** no fabricated "unseen label" positive case (`POL`/`Load Port` are already in the
table; `Loading Port`/`Origin Port` occur 0 times in data). No live SMTP. No `REVEAL_GT`.
Keep the app on a different host port than 8080 to avoid colliding with the inbox service.

## Edge cases owned here

| Case | Rule |
|---|---|
| `/submit` partial body | preflight blocks it; never submit without 520 keys |
| `scoring_available: false` | abort submit; `/secrets` mount missing |
| App starts before inbox | retry `/health` with backoff; fail loud after 60s |
| Container restart | `state/` and `outbox/` are host-mounted; checkpoint + learned aliases survive |
| Run crash mid-way | checkpoint resume; `/run` is idempotent |
| Port collision (8080 taken) | app port from env `APP_PORT` (default 8001) |
| Demo network failure at step 3 | cached LLM response + recorded clip |
| Windows Docker bind-mount path issues | repo must live under the user home (organizers' README note) |
| Submission written while run in progress | write to temp + `os.replace`; `/submission` serves the last complete file |

## Tests

- `test_server.py` — endpoint smoke with `TestClient`; `/run` stub produces 520 keys.
- `test_compose_config.py` — parse both compose files; assert service names/ports/env (guards against
  the `data-server:8080` mistake).
- `tools/preflight.py` — owned by Verification agent; Ops runs it, does not edit it.

## Definition of done (W5 gate)

1. `docker compose -f docker-compose.yml -f docker-compose.app.yml up` → app healthy, inbox healthy.
2. `SCORED_RUN=1` run produces `/state/submission.json`; preflight green; `POST /submit` → `n_emails == 520`.
3. Score recorded in `SUBMISSION.md` with stage1/stage3/e2e breakdown; e2e ≥ 0.95 (target 1.0).
4. Demo rehearsed twice end-to-end within the time budget; every step's fallback exists.
5. Restart test: `docker compose down && up` (or `restart app`) → checkpoint resume yields identical submission.
6. `REVEAL_GT` unset everywhere; no `/ground_truth` route reachable from the app.
7. `state/` and `outbox/` are host-mounted; `outbox/` is git-ignored; no `.eml` is ever sent.

## Dependencies

- Imports: everything (read-only), owns only its listed files.
- Blocked by: W4 gate. Never changes stage code; failures are filed against the owning agent.
- `app/outbox/` is **not** used — drafts go to the host-mounted `./outbox` volume via `$OUTBOX_DIR`.
