# Stage 1 — Classification

> Status: **DECIDED** (agreed 2026-09-19). This is the finalized architecture for the classification stage.
> Decision log: `DECISIONS.md` (D1–D9). Scoring weights: stage1 0.30 / stage3 0.20 / end-to-end 0.50.

## Placement in the pipeline

```
520 emails (inbox/*.json)
        │
        ▼
STAGE 1: CLASSIFICATION  ← this stage
        │  emits: category per email + decided_by (rule/sim/llm)
        ▼
Stage 2: EXTRACTION      (gate: only category == BL_COMPARISON passes)
        ▼
Stage 3: COMPARISON      (deterministic diff of the 7 fields)
```

## Stage contract

**Inbound:** raw email record `{email_id, from, subject, body, attachments[]}` — filenames only, attachments are never opened here (D9).

**Outbound (per email):**

```json
{"category": "BL_COMPARISON", "decided_by": "rule"}
```

- Categories (exact scorer vocabulary, `scoring.py:23`):
  `BL_COMPARISON | SI_REQUEST | INVOICE_QUERY | GENERAL | SPAM`
- `decided_by` is an internal extra — the scorer reads it for `rule_pct` for free (`scoring.py:55-59`); keep it in the submission payload.
- Never emits match/mismatch decisions — that belongs to later stages.

## Architecture: cascade classifier (D1, D2)

No trained ML model (520 samples, 5 classes, imbalanced → overfit risk). Four-stage cost funnel; ~85–90% resolved free, LLM sees ~2–6%.

```
email (from, subject, body, attachment filenames)
        │
── SIGNAL EXTRACTION (every email, free) ──
        │
signals = { has_SI, has_BL, n_att, is_reply, sender_domain,
            intent_check, intent_create, billing_terms, spam_score }
        │
        ▼
STAGE 0: HARD RULES (precision ~100%, decided_by="rule")
  spam_score high OR sketchy domain      → SPAM
  has_SI AND has_BL AND intent_check     → BL_COMPARISON
  SI only + check intent                 → BL_COMPARISON
      └ flag: missing_attachment (feeds Stage 2 review)
  billing terms, no doc intent           → INVOICE_QUERY
  unresolved → Stage 1 (~50–100 left)
        │
        ▼
STAGE 1: WEIGHTED EVIDENCE SCORE
  score[c] = Σ (signal × weight)  per class
  e.g. BL_COMPARISON = 3·(SI∧BL) + 2·intent_check
       SI_REQUEST    = 2·intent_create − (SI∧BL)
       SPAM          = 2·spam_score + domain_rep
  Decide iff: top ≥ ACCEPT  AND  margin = top−2nd ≥ MARGIN
              AND no conflict (check+create both fired)
  else → Stage 2 (~30–80 left)
        │
        ▼
STAGE 2: SEMANTIC SIMILARITY (tiebreaker, feeds back into Stage-1 scores)
  TF-IDF cosine: body vs 5 template centroids
  (centroids = 2–3 real body phrasings per class, from ~10 hand-read emails)
  Decide iff: best sim ≥ SIM_THRESHOLD and gap clear
              and no contradiction with evidence
  else → Stage 3 (~10–30 left)
        │
        ▼
STAGE 3: GLM-5.3-FLASH API (temp 0, JSON out, D4)
  5-shot prompt (one real example per class) + email
  → {"category", "confidence", "reason"}
  confidence ≥ 0.85 → decide, decided_by="llm"
  confidence < 0.85 → status=NEEDS_REVIEW (D7: never guess)
```

### Core principle (D3)

Classification uses **email metadata only**: subject, body, attachment filenames. Subjects are adversarial; body intent + attachment structure carry the signal.

## Prompt contract (Stage 3 LLM)

- Categories: exact scorer vocabulary above
- Definitions must emphasize: trust **body intent** over subject (misleading subjects are planted); `RE_` replies with no attachments can still be BL_COMPARISON
- Output: `{"category": ..., "confidence": 0.0–1.0, "reason": "one sentence"}`
- One client (GLM-5.3-flash) shared with extraction fallback; whole dataset ≈ $0.10–0.50

## Calibration loop (free)

1. Run cascade with thresholds wide open
2. `POST /submit` → read stage-1 macro-F1 + `rule_pct`
3. Tighten ACCEPT / MARGIN / SIM_THRESHOLD until rules resolve max emails without accuracy drop
4. Repeat — each submission costs nothing

## Verified dataset stats (computed from ground_truth.json, seed 42)

| Category | Count | Notes |
|---|---|---|
| BL_COMPARISON | 220 | 200 main set + 20 edge cases (email_501–520) |
| SI_REQUEST | 125 | bodies embed shipment details (irrelevant — exit here) |
| INVOICE_QUERY | 75 | |
| GENERAL | 60 | includes RPA bot notices, HR |
| SPAM | 40 | prize/phishing, sender domains are the giveaway |

- 46 defect emails (all in main set) — the end-to-end denominator
- All 20 NEEDS_REVIEW are email_501–520 (edge cases); main set has zero
- Baseline all-GENERAL submission = 0.0124 final; perfect classification alone caps at 0.30

## Traps owned by this stage

| Trap | Handling |
|---|---|
| Misleading subjects (email_004/052 "REQUEST BL DRAFT" subject, comparison body; 79/124 comparisons lack "CONFIRM DOCS") | Body-intent signals, never subject keywords |
| Reply threads, no attachments (43 `RE_` + CONFIRM DOCS, 23 with zero attachments) | Escalate on absence; classify by intent |
| Missing attachment (email_507 SI-only, email_495 none) | classify BL_COMPARISON + `missing_attachment` flag |
| Silent submission default (missing email scores as GENERAL) | Assert `len(submission)==520` before every submit |
| LLM output fragility (fenced/truncated JSON) | JSON-extraction regex + 1 retry + fallback NEEDS_REVIEW |
| Crash mid-run loses progress | Checkpoint results per email; resumable |
| Escalation over-trigger tanks escalation_precision | Tune 0.85 threshold via free submissions |
