# Plan 06 — Verification & Test Harness (owner: Verification agent)

> Scope: the independent oracle. Owns all `tests/`, `tools/verify_*.py`, `tools/preflight.py`,
> `tools/score_local.py`. **Never implements pipeline logic** — if a test needs a fix in a stage,
> file it with that stage's owner.

## Deliverable

A verification suite that can prove, without ground-truth field values, that extraction and
comparison are structurally correct; that every edge case lands on its expected outcome; and
that a submission is safe to POST before it is sent.

## Files owned

| File | Purpose |
|---|---|
| `tools/verify_extraction.py` | Structural oracle: agreement structure vs GT |
| `tools/verify_comparison.py` | e2e/stage3 local scoring + per-email diagnosis |
| `tools/verify_edges.py` | The 20 edge cases + zero-attachment BL class |
| `tools/preflight.py` | 520-key/invariant checks + `/health` + dry-run `/submit` |
| `tools/score_local.py` | Thin wrapper over `server/scoring.py` (no reimplementation) |
| `tools/ci.sh` | The CI gate sequence (see §5) |
| `tests/test_schema.py`, `test_normalize.py`, `test_checkpoint.py`, `test_state.py`, `test_run_stub.py`, `test_preflight.py`, `test_verify_structural.py` | Contract + harness tests |

> **Scope note:** this agent owns the harness (`tools/`) and the five contract test files
> (`test_schema`, `test_normalize`, `test_checkpoint`, `test_state`, `test_run_stub`) plus
> `test_preflight.py` / `test_verify_structural.py`. Stage-specific test files are owned by their
> plan agents (README matrix); this agent reviews and runs them but does not edit them.

## 1. Structural oracle (`verify_extraction.py`) — no GT values needed

`ground_truth.json` reveals **which** fields differ, never the values. So:

| GT says | Extraction must show | Failure means |
|---|---|---|
| `has_defect=false` | all 7 SI/BL pairs **equal** after compare-normalization | parser bug (over-mutation) |
| `defect_fields=[f]` | exactly `f` differs, all others equal | parser bug (missed/extraneous diff) |
| `NEEDS_REVIEW/wrong_doc_type` | no READY record for that email | sniff bug |
| `NEEDS_REVIEW/unreadable` | doc_status NEEDS_REVIEW | routing bug |
| `NEEDS_REVIEW/missing_value` | the expected field(s) null — **expectations hardcoded from the 5 SI files (§2a), not derivable from GT** | normalizer bug |
| `NEEDS_REVIEW/missing_attachment` | gate fired before parsing | gate bug |

Output: `email_id + field` for every mismatch between structure and GT. Exit non-zero on any.
Scope flag: `--scope txt` (W2) evaluates txt pairs only; default evaluates all (W3+).

## 2. Golden expectations (exact, verified against `data_v2`)

**Edge cases 501–520 (all `BL_COMPARISON`):**

| IDs | status | review_reason |
|---|---|---|
| 501–505 | NEEDS_REVIEW | wrong_doc_type |
| 506–510 | NEEDS_REVIEW | missing_attachment |
| 511–515 | NEEDS_REVIEW | unreadable |
| 516–520 | NEEDS_REVIEW | missing_value |

**§2a — 516–520 per-field null expectations (derived from the SI files; NOT in GT):**

| Email | Null fields (SI side) | Non-null check |
|---|---|---|
| 516 | gross_weight_kg (`N/A`) | all other 6 present |
| 517 | port_of_loading (`____MT`), port_of_discharge (`TBA`) | 5 present |
| 518 | port_of_discharge (`N/A`), gross_weight_kg (`____MT`) | 5 present |
| 519 | shipper (blank), container_count (blank) | 5 present |
| 520 | consignee (blank) | 6 present |

`NET WEIGHT: ???/_______ MTS` must be ignored everywhere (it is not `gross_weight_kg`).

**46 defect emails (all main set) — exact `defect_fields`:**

```
004 consignee,notify_party      013 port_of_discharge         025 container_count,port_of_discharge
031 container_count,gross_weight_kg                          043 container_count
046 notify_party                065 notify_party,port_of_discharge
071 container_count,port_of_discharge                        091 container_count
097 container_count,gross_weight_kg                          107 consignee,container_count
111 container_count             119 port_of_loading           121 gross_weight_kg
128 gross_weight_kg,port_of_loading                          129 port_of_discharge,port_of_loading
133 gross_weight_kg             144 consignee,container_count 145 shipper
174 notify_party,port_of_discharge                           178 container_count
182 container_count,port_of_discharge                        225 consignee
243 port_of_discharge,port_of_loading                        256 port_of_discharge,shipper
270 port_of_discharge           291 consignee,container_count 300 notify_party,shipper
302 container_count             312 notify_party,shipper       313 container_count,gross_weight_kg
324 container_count,shipper     334 consignee,shipper         342 container_count,notify_party
351 container_count,gross_weight_kg                          354 gross_weight_kg,notify_party
361 gross_weight_kg,port_of_discharge                        379 shipper
410 port_of_loading             416 gross_weight_kg           426 container_count,port_of_discharge
434 port_of_discharge           435 gross_weight_kg           468 container_count,port_of_loading
481 consignee                   499 gross_weight_kg
```

**Binary defect inventory (13 emails):**

| Email | Attachments | defect_fields |
|---|---|---|
| 097 | xlsx + docx | container_count, gross_weight_kg |
| 107 | xlsx + docx | consignee, container_count |
| 243 | xlsx + xlsx | port_of_discharge, port_of_loading |
| 291 | xlsx + docx | consignee, container_count |
| 300 | xlsx + xlsx | notify_party, shipper |
| 302 | xlsx + docx | container_count |
| 313 | pdf + pdf | container_count, gross_weight_kg |
| 351 | pdf + pdf | container_count, gross_weight_kg |
| 354 | xlsx + docx | gross_weight_kg, notify_party |
| 434 | pdf + pdf | port_of_discharge |
| 435 | xlsx + docx | gross_weight_kg |
| 481 | xlsx + xlsx | consignee |
| 499 | pdf + pdf | gross_weight_kg |

**Other gold facts:** statuses overall 454 OK / 46 MISMATCH / 20 NEEDS_REVIEW; BL partition 94
zero-att (91 OK + 3 NR), 2 SI-only (NR), 124 two-att (63 OK / 46 MISMATCH / 15 NR); txt-only
defects 33, binary defects 13; txt-only OK pairs **51**, binary OK pairs **12** (005, 055, 059, 160,
171, 208, 273, 398, 407, 411, 462, 496); all-GENERAL baseline final = 0.0124; txt-core-perfect
e2e = 0.7174 (33/46); **23 INVOICE_QUERY bodies also match `dropped|still missing`** (category gate
must prevent false escalations); mojibake files = 8 (160_SI, 208_SI, 208_BL, 273_BL, 313_BL,
351_SI, 411_SI, 411_BL); 56 files carry an `ON BEHALF OF` chain; 4 prefix-related party defects
(145/256/312/379) must be flagged, not escalated.

## 3. `preflight.py` (run before every submit — pinned order, matches `../ARCHITECTURE.md` §4)

1. `GET /health` → `emails == 520`, `scoring_available == true` (else abort before anything else).
2. `assert len(sub) == 520` and `set(sub) == set(email_ids)`.
3. Every value has exactly the required keys; `category ∈ CATEGORIES`;
   `review_reason ∈ REVIEW_REASONS ∪ {None}`; `has_defect == (status == "MISMATCH")`.
4. Dry-run: POST `sample_submission.json`; expect `final_score ≈ 0.0124` and `n_emails == 520`.
5. Real submit → assert returned `n_emails == 520`.
6. `docker compose down && up` → re-run step 4 to prove state survives (Ops executes; Verification owns the check).

## 4. Test matrix (per owner; the verification agent gates)

| Test file | Owner plan | What it proves |
|---|---|---|
| `test_schema.py`, `test_normalize.py`, `test_checkpoint.py`, `test_state.py`, `test_run_stub.py` | 00 (contract tests written & owned by 06) | contracts + v3-A2/A3/A4 normalization + gate ordering |
| `test_signals.py`, `test_stage1_rules.py`, `test_stage1_llm.py`, `test_calibration.py` | 01 | cascade behavior, zero-att BLs, cache-only frozen run |
| `test_aliases.py`, `test_txt_parser.py`, `test_txt_normalize.py` | 02 | 100% alias coverage; blanks; CJK; indentation guard |
| `test_doctype.py`, `test_xlsx_parser.py`, `test_docx_parser.py`, `test_pdf_parser.py`, `test_binary_failures.py` | 03 | unitless weight, mojibake, corrupt/image-only, separators |
| `test_compare.py`, `test_compare_real.py`, `test_port_semantics.py`, `test_on_behalf_of.py` | 04 | exact-set discipline, port name rule, literal-token guard |
| `test_alias_learning.py`, `test_review_queue.py`, `test_llm_fallback.py`, `test_draft_email.py`, `test_scored_run.py`, `test_no_smtp.py`, `test_extension_isolation.py` | 05 | guardrails G1–G10 |
| `test_preflight.py`, `test_verify_structural.py` | 06 | oracle correctness on synthetic fixtures |
| `test_server.py`, `test_compose_config.py` | 07 | endpoint smoke, compose port/service guard |

## 5. CI gate (`tools/ci.sh` — run by Verification agent before any wave gate)

```
pytest tests/ -q                                  # unit suite
python tools/verify_extraction.py --data data_v2  # structural oracle (--scope txt at W2)
python tools/verify_edges.py --data data_v2       # 20 edges + 94 zero-att class + 23 negatives
python tools/verify_comparison.py --data data_v2  # local score report
python tools/preflight.py submission.json         # submission safety (steps 1–2 offline; 3–6 need Docker)
```

Offline vs Docker: steps 1–2 of preflight and the full test suite run offline; preflight steps 3–6
need the organizers' Docker server. The W0/W5 gates require Docker; W1–W4 do not.

## Definition of done (W0/W1/W2/W3/W4/W5 gates)

1. Structural oracle: **zero** email/field mismatches at W3; at W2, only known-binary emails may differ.
2. Edge verifier: 20/20 edges exact; all 94 zero-attachment BLs `BL_COMPARISON`/OK except the 3;
   23 INVOICE_QUERY phrase-matches stay non-escalated.
3. Local score: W1 stage1 macro-F1 ≥ 0.95 (rules+sim+cache); W2 e2e ≥ 0.70; W3 stage3 F1 ≥ 0.95 and e2e ≥ 0.95.
4. `preflight.py` green and dry-run `/submit` returns `n_emails == 520`.
5. Every test file above exists, is owned, and is green — no skipped tests at a gate.
6. W4 gate: `test_extension_isolation.py` proves a byte-identical submission under `SCORED_RUN=1`.

## Dependencies

- Imports: `server/scoring.py` (read-only), `app.schema`, `app.normalize`, stage modules (read-only).
- Never edits stage files; failures are filed against the owning agent with `email_id + field`.
