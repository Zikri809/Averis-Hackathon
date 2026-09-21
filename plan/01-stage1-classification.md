# Plan 01 — Stage 1: Classification (owner: Classification agent)

> Scope: category per email from metadata only. Never opens attachments (D9, D3).
> Scoring: stage1 = 0.30 of final. Verified counts: BL 220 / SI_REQUEST 125 / INVOICE 75 / GENERAL 60 / SPAM 40.

## Deliverable

A cascade classifier producing `{"category", "decided_by"}` for all 520 emails with stage1
macro-F1 ≥ 0.95 on the local scorer. Rules resolve the bulk for free; the LLM sees the rest.

## Files owned

| File | Purpose |
|---|---|
| `app/stage1_classify.py` | Cascade: Stage 0 rules → Stage 1 evidence → Stage 2 similarity → Stage 3 LLM |
| `app/signals.py` | Signal extraction from `{from, subject, body, attachments[]}` |
| `app/categories.py` | Category vocabulary + template centroids |
| `app/llm_client.py` | GLM-flash client + frozen cache (`state/llm_cache.json`) + JSON extraction/retry |

## Contracts

**Inbound:** `EmailRecord = {email_id, from, subject, body, attachments[]}` (filenames only).

**Outbound:** `{"category": CAT, "decided_by": "rule"|"sim"|"llm"}`; uncertain → the same record
with category `GENERAL` is **wrong** — instead emit category per best evidence but never escalate
here: `NEEDS_REVIEW` is an extraction status, not a category. When confidence < 0.85, emit the
best category with `decided_by="llm"` and let the extraction gate handle unknowns. (Category must
always be one of the 5; a missing category scores as GENERAL.)

## Tasks

| # | Task | Verification |
|---|---|---|
| C1 | `signals.py`: `has_SI`, `has_BL` (filename regex `_SI`/`_BL`), `n_att`, `is_reply` (`^RE[_:]`), `sender_domain`, `intent_check` (compare/confirm/check phrases), `intent_create` (request/issue/create SI), `billing_terms` (invoice/payment), `spam_score` (prize/phishing/domain) | `pytest tests/test_signals.py` with real samples 004, 052, 495, 506 |
| C2 | Stage 0 hard rules (precision-first): spam domain → SPAM; `has_SI ∧ has_BL ∧ intent_check` → BL_COMPARISON; `SI only ∧ check` → BL_COMPARISON; billing w/o doc intent → INVOICE_QUERY | confusion matrix on 520 shows zero SPAM→other and zero BL→SPAM at rules layer |
| C3 | Stage 1 weighted evidence with ACCEPT/MARGIN + conflict guard | `tools/score_local.py --stage1` reports rule_pct + macro-F1 |
| C4 | Stage 2 TF-IDF centroids (2–3 bodies/class from hand-read emails) | sim layer resolves cases without accuracy drop |
| C5 | `llm_client.py`: GLM flash 5-shot, temp 0, JSON out, retry + fallback; **cache every response to `state/llm_cache.json` keyed by `sha256(subject+body)`** | `pytest tests/test_stage1_llm.py` with mocked client + cache replay |
| C6 | Calibration loop: widen thresholds → submit → tighten; **record the LLM cache during calibration, then freeze it** | `rule_pct` maximized subject to macro-F1 ≥ 0.95; gate re-run with `SCORED_RUN=1` (cache only) still ≥ 0.95 |

## Edge cases owned here

| Case | Rule |
|---|---|
| Misleading subject ("REQUEST BL DRAFT" but comparison body; 79/124 comparisons lack "CONFIRM DOCS") | **Never use subject keywords as decision signals**; body intent only |
| Reply thread, zero attachments (94 BL emails, 91 OK) | `has_SI/has_BL` false — must still classify BL_COMPARISON via body intent. Do **not** treat "no attachment" as evidence against BL_COMPARISON |
| Zero-attachment BL body variants | 91 OK bodies say "send the draft BL … for checking" (no "compare"); the 3 NR bodies say `dropped`/`still missing`. Both must classify BL_COMPARISON; the gate in `run.py` (Foundation) handles the escalation |
| Missing attachment phrasing (506/508/510) | Body contains `dropped`/`still missing`; classification stays BL_COMPARISON; the escalation gate lives in `run.py` (Foundation, plan 00) |
| GENERAL "reminder" subjects containing doc words (`_Reminder_Paper - Submit SI & AED`, 11 emails; `Pending BL Release` 7; `Outstanding BL` 2) | Must classify GENERAL: require intent **directed at this mailbox** (compare/confirm/request draft), not generic reminders; no attachments + no compare verb → GENERAL |
| INVOICE_QUERY bodies matching `dropped`/`still missing` (23 emails) | Classification must still be INVOICE_QUERY (billing terms win); the Foundation gate is category-gated so it cannot misfire |
| SPAM "Re: Invoice payment - kindly confirm your bank details" (2 emails) | `spam_score` at rules layer wins over billing/confirm words; assert these 2 are SPAM |
| SI_REQUEST bodies embed shipment details | Shipment detail mentions are not doc-intent; require request/create intent |
| Spam with doc-like wording | `spam_score` at rules layer wins over weak doc intent |
| External senders with doc requests | `sender_domain` is a signal, not a gate: EXTERNAL_CONTACTS also send BL_COMPARISON; do not route external → SPAM |
| LLM returns fenced/truncated JSON | regex extract → 1 retry → fallback `GENERAL` with `decided_by="llm"`; cache only successful parses |
| API timeout / rate limit | per-email try/except; checkpoint before advancing; resume safe; **cache miss under `SCORED_RUN=1` falls back to rules/sim decision, never a live call** |

## Tests

- `test_signals.py` — real emails: 004/052 (misleading subject), 495 (zero-att OK), 506 (dropped), 001 (clean comparison), 11 reminder GENERALs, 23 INVOICE_QUERY phrase matches, 2 SPAM bank-detail mails.
- `test_stage1_rules.py` — rules-only confusion matrix; assert no SPAM leaks into BL_COMPARISON; assert the 94 zero-att BLs are BL_COMPARISON.
- `test_stage1_llm.py` — mocked client: valid JSON, fenced JSON, truncated JSON, 500 error; cache hit/miss under `SCORED_RUN=1`.
- `test_calibration.py` — thresholds sweep on cached signals; assert `rule_pct` rises monotonically with threshold tightening without macro-F1 loss.

## Definition of done (W1 gate)

1. `tools/score_local.py --stage1 submission.json` → `stage1.macro_f1 ≥ 0.95`, `accuracy ≥ 0.95` **with `SCORED_RUN=1`** (rules + sim + frozen cache; no live LLM).
2. `rule_pct` reported (not None) and ≥ 0.60.
3. All 94 zero-attachment BL emails classified `BL_COMPARISON`; the 11 reminder GENERALs stay GENERAL.
4. `pytest tests/test_signals.py tests/test_stage1_*.py tests/test_calibration.py -q` green.
5. No attachment bytes opened in this stage (assert in test: monkeypatch `read_bytes` to raise).
6. `state/llm_cache.json` exists, is deterministic, and is committed with the submission artifacts.

## Dependencies

- Imports: `schema`, `state` (Foundation). Never imports Stage 2/3.
- Consumed by: `run.py` (Foundation) only.
