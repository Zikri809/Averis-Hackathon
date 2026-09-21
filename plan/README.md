# SDOC Implementation Plan

> **Source of truth:** `../ARCHITECTURE.md` (v3). This directory turns it into executable,
> owner-assigned work. Read `../ARCHITECTURE.md` §1 (corrections register) and §3 (verdicts)
> before touching any stage plan.

## How to use this plan

1. Work the **waves in order** (see roadmap). A wave's gate must pass before the next wave starts.
2. Every plan file has: **scope, contracts, owned files, tasks with owners, edge cases, tests,
   definition of done**. Do not implement beyond scope.
3. **One writer per file.** Ownership is exclusive; tests are the one exception (see below).
   Cross-file changes are requested through the interface owner. Never edit another owner's file.
4. Every task has a **verification command**; "works on my machine" is not done.
5. Run the **edge-case coverage register** check at the end of every wave.

## Ownership matrix (each subagent is responsible for one part)

| # | Subagent (role) | Owns (exclusive) | Plan file |
|---|---|---|---|
| 0 | **Foundation agent** | `sdoc-hackathon-docker/app/loader_client.py`, `state.py`, `checkpoint.py`, `normalize.py`, `schema.py`, `run.py`, package inits (`app/__init__.py`, `app/stage2/__init__.py`, `app/extensions/__init__.py`) | `00-foundation.md` |
| 1 | **Classification agent** | `app/llm_client.py`, `app/stage1_classify.py`, `app/signals.py`, `app/categories.py`, `tests/test_signals.py`, `tests/test_stage1_*.py`, `tests/test_calibration.py` | `01-stage1-classification.md` |
| 2 | **Text extraction agent** | `app/stage2/router.py`, `app/stage2/txt_parser.py`, `app/stage2/aliases.py`, `tests/test_aliases.py`, `tests/test_txt_*.py` | `02-stage2-text.md` |
| 3 | **Binary extraction agent** | `app/stage2/xlsx_parser.py`, `app/stage2/docx_parser.py`, `app/stage2/pdf_parser.py`, `app/stage2/doctype.py`, `app/stage2/binary_parsers.py`, `tests/test_xlsx_parser.py`, `tests/test_docx_parser.py`, `tests/test_pdf_parser.py`, `tests/test_binary_failures.py`, `tests/test_doctype.py` | `03-stage2-binary.md` |
| 4 | **Comparison agent** | `app/stage3_compare.py`, `app/stage3_normalize.py`, `tests/test_compare*.py`, `tests/test_port_semantics.py`, `tests/test_on_behalf_of.py` | `04-stage3-comparison.md` |
| 5 | **Extensions agent** | `app/extensions/*` (excluding `__init__.py`), `app/ui/*`, `tests/test_alias_learning.py`, `tests/test_review_queue.py`, `tests/test_llm_fallback.py`, `tests/test_draft_email.py`, `tests/test_scored_run.py`, `tests/test_no_smtp.py`, `tests/test_extension_isolation.py` | `05-extensions.md` |
| 6 | **Verification agent** | `tools/verify_*.py`, `tools/preflight.py`, `tools/score_local.py`, `tools/ci.sh`, `tests/test_schema.py`, `tests/test_normalize.py`, `tests/test_checkpoint.py`, `tests/test_state.py`, `tests/test_run_stub.py`, `tests/test_preflight.py`, `tests/test_verify_structural.py` | `06-verification.md` |
| 7 | **Ops/Demo agent** | `app/server.py`, host `outbox/`, `sdoc-hackathon-docker/Dockerfile.app`, `sdoc-hackathon-docker/docker-compose.app.yml`, `DEMO.md`, `SUBMISSION.md`, `tests/test_server.py`, `tests/test_compose_config.py` | `07-deploy-demo.md` |

**Test-file ownership:** each plan owns the tests listed in its row; the Verification agent owns the
harness (`tools/`), the contract tests (`test_schema/normalize/checkpoint/state/run_stub`), and the
gate — it reviews and runs other agents' tests but does not edit them. All paths are relative to
`sdoc-hackathon-docker/` unless stated otherwise.

**Interface ownership rules:**

- `schema.py` (Foundation) defines every record shape. Any change to a record shape is a Foundation
  task + a broadcast to all owners; version the schema (`SCHEMA_VERSION`).
- `normalize.py` (Foundation) owns string normalization and KG/unit helpers — Stage 2 and Stage 3
  import it, never re-implement it. **v3-A2/A3/A4 live here and are Foundation tasks.**
- `aliases.py` (Text agent) is the single alias table. `router.register(ext, fn)` is published by
  the Text agent in `router.py`; the Binary agent **calls** it from its own parser modules'
  `register_all(router)` function — it never edits `router.py`.
- `doctype.py` (Binary agent) is the shared doc-type sniff. Text agent calls it; does not implement it.
- `checkpoint.py` (Foundation) keys on `email_id + sha256(attachment bytes) + alias_table_hash +
  learned_alias_hash + SCHEMA_VERSION`. Extension agents must not change that key without
  Foundation sign-off.
- `run.py` (Foundation) is the only orchestrator. Extension wiring into it is a Foundation task (F7);
  extension agents verify only.

## Frozen-run semantics (`SCORED_RUN=1`)

The frozen submission run is **deterministic and offline**:

| Component | Behavior under `SCORED_RUN=1` |
|---|---|
| Stage 1 rules + similarity | Runs normally |
| Stage 1 LLM (GLM flash) | **Disabled** — cached per-email responses from `state/llm_cache.json` are used; cache miss → the rules/sim decision stands. The cache is recorded once during calibration (W1) and frozen with the submission |
| Stage 2 LLM label fallback | Disabled |
| Learned aliases | Not loaded |
| OCR | Not used (never was, E5) |
| Draft email | Not written |

**Consequence for W1:** the gate must be met with **rules + similarity alone** against the frozen
cache; the LLM may only be used during calibration, never as a crutch in the gate. Plan 01 C6 owns
recording the cache; plan 06 asserts it.

## Wave roadmap (gates from `../ARCHITECTURE.md` §5)

| Wave | Deliverable | Gate to pass before next wave | Owners |
|---|---|---|---|
| **W0** | Skeleton, schema, loader, checkpoint, normalization | `tools/preflight.py` green against `data_v2`; first `POST /submit` with baseline submission returns HTTP 200 | 0, 6, 7 |
| **W1** | Classification (rules + sim; LLM cache recorded) | stage1 macro-F1 ≥ 0.95 with rules+sim+cache, `rule_pct` reported | 1, 6 |
| **W2** | Text extraction + comparison (txt core); all binary formats routed to `NEEDS_REVIEW/unreadable` | e2e ≥ 0.70 (txt defects 33/46 → ceiling 0.7174); zero false positives on the 51 txt OK pairs | 2, 3 (B1/B6; B2–B5/B7 may begin once `aliases.py` lands), 4, 6 |
| **W3** | Binary extraction (xlsx/docx/pdf) | e2e ≥ 0.95; stage3 defect-F1 ≥ 0.95 | 3, 6 |
| **W4** | Extensions (review queue, alias learning, LLM fallback, draft email) — **all default-off** | extensions do not change a frozen-run submission byte-for-byte | 5, 6 |
| **W5** | Deploy, demo, final frozen submission | `preflight` + 520-key assert + `n_emails == 520` + recorded demo | 7, 6 |

**Rules:** no W4 work until W3 gate passes. No binary parser work (B2–B5, B7) before the Text agent's
`aliases.py` (02 T1) lands — B1 (`doctype.py`) and B6 (failure paths) start immediately since they do
not depend on the alias table. W2's binary stub route (`02` T3) is replaced at W3 without editing
`router.py`.

## Edge-case coverage register (must all be green before final submission)

Each edge class has a **primary owner** and optional contributors. The verification agent asserts
them all from `ground_truth.json` (except where noted in `06-verification.md` §2a).

| Edge class | Email IDs | Primary owner | Contributors | Expected outcome |
|---|---|---|---|---|
| Impostor doc | 501–505 | 3 (doctype) | 2 (router) | `NEEDS_REVIEW/wrong_doc_type` |
| Zero attachments + dropped phrasing | 506, 508, 510 | 0 (gate in `run.py`) | 1 (classification), 2 (evidence only) | `NEEDS_REVIEW/missing_attachment` |
| SI-only | 507, 509 | 0 (gate in `run.py`) | 1 | `NEEDS_REVIEW/missing_attachment` |
| Corrupt PDF | 511_BL, 515_BL | 3 (pdf parser) | — | `NEEDS_REVIEW/unreadable` |
| Image-only PDF | 512, 513, 514 | 3 (pdf parser) | — | `NEEDS_REVIEW/unreadable` |
| Blank values | 516–520 | 2 (txt normalizer) | 0 (blank tokens) | `NEEDS_REVIEW/missing_value` |
| Zero-attachment but OK | 94 emails incl. 495 | 1 (classification) | 0 (gate ordering) | `BL_COMPARISON`, status `OK` |
| Binary defects | 097,107,243,291,300,302,313,351,354,434,435,481,499 | 3 | — | exact `defect_fields` |
| CJK label | 51 files / 43 emails (e.g. 013, 043, 243_BL, 519) | 2 (aliases) | 3 (binary callers) | weight extracted |
| Mojibake TOTAL | 160, 208, 273, 313, 351, 411 (8 files) | 3 (pdf) | — | weight extracted from TOTAL line |
| LOCODE-identical port defect | 15 pairs / 16 instances | 4 (compare) | 2/3 (parse) | port defect caught by name |
| ON BEHALF OF chain | 520 + 55 other files | 2 + 4 | — | review, not defect |
| Indented continuation with colon | 144 (both sides) | 2 | — | address line never parsed as label |
| Multi-line values | addresses everywhere, 520 | 2 | — | continuation lines absorbed |

## Global conventions

- Python 3.13, stdlib + `openpyxl`, `python-docx`, `pymupdf`. No other deps without Foundation sign-off.
- All file reads: `encoding='utf-8', errors='replace'` (win32 charmap trap).
- The frozen run is deterministic and offline; see "Frozen-run semantics" above.
- Every stage is a pure function of its inputs; I/O only in `run.py` (Foundation) and `server.py` (Ops).
- Failures are isolated per email and per file; the run always completes with 520 results.
- Every module ships with unit tests in the same PR; the verification agent gates the merge.
