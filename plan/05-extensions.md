# Plan 05 — Extensions (owner: Extensions agent)

> Scope: review queue, alias learning, bounded LLM label fallback, auto-draft clarification email.
> **All four are default-OFF and must never influence a scored run.** `SCORED_RUN=1` disables
> everything in this plan. These move rubric lines (Practical Value, Innovation, System Design),
> not `final_score` — build them only after the W3 gate.

## Deliverable

A demo-credible layer on top of the frozen pipeline: a review UI over escalations, reviewer
corrections that can teach the alias table, a bounded label fallback with visible confidence,
and a draft-only clarification email outbox.

## Files owned

| File | Purpose |
|---|---|
| `app/extensions/review_queue.py` | Queue projection over escalations + resolution actions |
| `app/extensions/alias_learning.py` | Append-only learned aliases + validation + precedence |
| `app/extensions/llm_label_fallback.py` | One-call label mapping, threshold 0.90 |
| `app/extensions/draft_email.py` | Templated `.eml` writer from `diff_report` |
| `app/ui/` | Static HTML/JS review dashboard (no framework, no CDN dependency) |

## Hard guardrails (non-negotiable)

| ID | Guardrail |
|---|---|
| G1 | `SCORED_RUN=1` ⇒ learned aliases not loaded, LLM fallback not called, OCR never used, draft email not written |
| G2 | Learned aliases live in `state/alias_learned.jsonl` (host-mounted); **never** write `pools.py` or `aliases.py` |
| G3 | Precedence: generator alias table **>** learned aliases; learned only fills gaps |
| G4 | Learned alias disabled if normalized label collides with a different canonical field, contains, or is contained by an existing alias |
| G5 | Learned-file hash enters the checkpoint key (`LEARNED_ALIAS_HASH`, Foundation F4) so re-runs re-parse |
| G6 | LLM fallback fires only when: label unmatched AND value is type-compatible with a target field AND that field is currently `null` AND the email is not a NEEDS_REVIEW edge case. Never for known non-fields (`NET WEIGHT`, `Export Carrier`, `Freight`, `HS Code`, `OC No.`, `Vessel`, `Voyage`, `Commodity`, `Booking`, `BL No.`, `Country of Origin`) |
| G7 | LLM accept threshold ≥ 0.90; below → falls through to existing `missing_value` path; one call per unmatched label; cached; timeout → `missing_value` |
| G8 | Draft email: `.eml` to `$OUTBOX_DIR` (host-mounted `./outbox`, owned by plan 07) only — **no SMTP code anywhere in the repo**; only for `status == MISMATCH`; recipient = `From:` of the BL-carrying email verbatim; `Booking Ref` from attachment evidence if present else omit; banner "DRAFT — NOT SENT" |
| G9 | Review UI is display + local-write only; it must never read `ground_truth.json` (no `/ground_truth`, no `REVEAL_GT`) |
| G10 | Confidence is display-only: assert no Stage 2/3 branch reads it (test) |

## Tasks

| # | Task | Verification |
|---|---|---|
| X1 | `alias_learning.py`: append-only JSONL, two-phase (proposal `confirmed:false` → apply `confirmed:true`), atomic `os.replace` + file lock, validation per G4, `load()` returns only confirmed entries | `pytest tests/test_alias_learning.py`: poison attempts rejected; concurrent writes safe; precedence test |
| X2 | `review_queue.py`: projection `email_id, review_reason, raw label, snippet, confidence, file link`; actions confirm/correct/confirm-escalation | `pytest tests/test_review_queue.py`; 20 edge emails all appear with correct reason |
| X3 | `llm_label_fallback.py`: strict JSON `{field|none, confidence}`, threshold 0.90, type-compat gate, cache, timeout path | `pytest tests/test_llm_fallback.py` with mocked client: accept, reject, timeout, malformed |
| X4 | `draft_email.py`: template from `diff_report`, `.eml` writer, booking-ref lookup, DRAFT banner | `pytest tests/test_draft_email.py`; no SMTP import anywhere (grep test) |
| X5 | `app/ui/`: queue table + resolution form + draft preview; static assets vendored (no CDN) | manual smoke: open `http://localhost:8001/` (ops agent serves it) |
| X6 | **Verify** (do not edit `run.py`): each extension entry point is a no-op under `SCORED_RUN=1`; the wiring itself is Foundation task F7 | `pytest tests/test_scored_run.py`; `test_extension_isolation.py` byte-compare |

## Edge cases owned here

| Case | Rule |
|---|---|
| Reviewer correction collides with existing alias | reject, show why (G4) |
| Reviewer correction for a non-field label (`NET WEIGHT`) | reject (G4/G6) |
| Two reviewers write simultaneously | file lock + append-only; no lost writes |
| Container restart | `state/` is host-mounted; learned aliases survive; UI reads them |
| Fallback fires on a clean email | impossible by G6 (only fills a currently-null field on a non-edge email) |
| Fallback returns low confidence | `missing_value` path unchanged; no silent accept |
| Fallback network failure during demo | cached response or graceful decline; never blocks the run |
| Draft email for a NEEDS_REVIEW case | forbidden (G8) |
| Draft recipient is an internal forwarder | recipient is `From:` verbatim; banner requires ops review |
| Draft contains no booking ref | omit the `{ref}` line, do not invent |
| Demo alias learning on a real email | must not be the 520-run; use the pre-seeded case |
| `ground_truth.json` reachable | UI must not link or fetch it (G9) |

## Tests

- `test_alias_learning.py`, `test_review_queue.py`, `test_llm_fallback.py`, `test_draft_email.py`, `test_scored_run.py`.
- `test_no_smtp.py` — grep repo for `smtplib|sendmail|smtp`; fail on any hit.
- `test_extension_isolation.py` — run `run.py` with and without extensions: submission JSON byte-identical.

## Definition of done (W4 gate)

1. `SCORED_RUN=1 python -m app.run ...` output is **byte-identical** to the W3 frozen submission.
2. All 20 edge emails appear in the review queue with the correct `review_reason`.
3. Alias learning demo: correction → proposal → apply → learned file gains entry → restart preserves it.
4. `NET WEIGHT` negative control: fallback declines with confidence below threshold visible.
5. Draft email for `email_313` (or 097) writes `outbox/email_313.eml` with "DRAFT — NOT SENT".
6. No SMTP code; no ground-truth access; `pytest tests/test_*extension* tests/test_alias_learning.py tests/test_scored_run.py tests/test_no_smtp.py -q` green.

## Dependencies

- Imports: `schema`, `state`, `normalize` (Foundation), `aliases` (Text agent), reads `Verdict`/`diff_report` (Comparison agent).
- `run.py` wiring is Foundation task F7; this plan's modules must be importable without side effects
  and must expose `is_enabled()` so F7 can gate them.
- `state/alias_learned.jsonl` and `state/alias_proposals.jsonl` live on the host-mounted `./state`
  volume (Ops agent, plan 07 O2).
