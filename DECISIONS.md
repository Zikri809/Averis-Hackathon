# SDOC Hackathon — Confirmed Architecture Decisions

> Shipping Document Verification pipeline. Status: agreed 2026-09-19.
> Scoring reference: `server/scoring.py` — weights: stage1 0.30 / stage3 0.20 / **end-to-end 0.50**.

---

## Decision Log

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | No trained ML classifier (xgboost etc.) | 520 samples, 5 classes, imbalanced → overfit risk; rules+LLM cascade is more robust |
| D2 | Cascade classifier: rules → evidence score → similarity → flash LLM | Cost funnel; ~85–90% resolved free, LLM sees ~2–6% |
| D3 | Classification uses **email metadata only** (subject, body, attachment filenames) | Subjects are adversarial; body intent + attachment structure carry the signal |
| D4 | LLM = GLM-5.3-flash API, temp 0, strict JSON out | Cheap (~$0.10–0.50 for whole dataset); one client for classify + extraction fallback |
| D5 | Local OCR = GLM-OCR (0.9B) via Docker + vLLM on RTX 4050 6GB | Privacy story for judges ("docs never leave machine"); fits 4GB VRAM requirement |
| D6 | Comparison is **deterministic code**, never LLM | Reproducible, explainable, debuggable |
| D7 | Uncertainty → `NEEDS_REVIEW`, never guess | Reliability axis (`escalation_f1`) is a scored metric |
| D8 | Keep `decided_by` field (rule/sim/llm) per email | Scorer reports `rule_pct` for free; demo artifact |
| D9 | OCR NOT in classification pathway — lives in extraction, gated by classifier output | Only ~6 scanned PDFs exist; avoids burning GPU on spam |

---

## Pathway A — Classification (metadata only)

```
520 emails (from, subject, body, attachments[])
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
      └ status=NEEDS_REVIEW, reason=missing_attachment
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
STAGE 3: GLM-5.3-FLASH API (temp 0, JSON out)
  5-shot prompt (one real example per class) + email
  → {"category", "confidence", "reason"}
  confidence ≥ 0.85 → decide, decided_by="llm"
  confidence < 0.85 → status=NEEDS_REVIEW
```

### Classification prompt contract (GLM-5.3-flash)

- Categories: `BL_COMPARISON | SI_REQUEST | INVOICE_QUERY | GENERAL | SPAM` (exact scorer vocabulary, `scoring.py:23`)
- Definitions in prompt must emphasize: trust **body intent** over subject (misleading subjects are planted); RE_ replies with no attachments can still be BL_COMPARISON
- Output: `{"category": ..., "confidence": 0.0–1.0, "reason": "one sentence"}`

### Calibration loop (free)

1. Run cascade with thresholds wide open
2. `POST /submit` → read stage-1 macro-F1 + `rule_pct`
3. Tighten ACCEPT / MARGIN / SIM_THRESHOLD until rules resolve max emails without accuracy drop
4. Repeat — each submission costs nothing

---

## Pathway B — Extraction (gated: BL_COMPARISON only, ~124 emails)

Per-attachment router:

| Type | Path |
|------|------|
| `.txt` | read (utf-8, errors=replace) → content-sniff title → SI/BL parser or wrong_doc_type |
| `.docx` | python-docx → paragraph + table scan → SI/BL parser |
| `.xlsx` | openpyxl → cell scan for 7 field labels |
| `.pdf` | pymupdf → text layer? |
| ├ yes | → content-sniff → text parser |
| └ no (image-only) | → render page @150–200 dpi → **local GLM-OCR (Docker/vLLM)** → text parser |
| corrupt | → `NEEDS_REVIEW`, reason=`unreadable` |

Output per doc: 7-field JSON with `null` for genuinely absent fields.

### Extraction prompt contract (LLM fallback for messy docs)

```json
{"shipper": str|null, "consignee": str|null, "notify_party": str|null,
 "port_of_loading": str|null, "port_of_discharge": str|null,
 "container_count": int|null, "gross_weight_kg": float|null,
 "readable": bool, "notes": "unparsed labels/ambiguities"}
```

- null = field genuinely absent, never guess
- Synonym mapping in prompt ("Load Port" → port_of_loading, "Gross Weight" → gross_weight_kg)

### GLM-OCR serving (carried over from user's other project)

```bash
vllm serve zai-org/GLM-OCR \
     --speculative-config.method mtp \
     --speculative-config.num_speculative_tokens 1
# OpenAI-compatible API :8000
# client: image_url = base64 data URI of rendered page, prompt "Text Recognition:",
#         temperature=0.0, max_tokens=2048
```

- GLM-OCR is OCR-only (image → text); parsed text then flows into the same field extractor
- OCR failure → `unreadable` review case, never a guess

---

## Pathway C — Comparison (pure deterministic code)

1. Normalize: `upper()`, strip punctuation, alias tables for ports
2. Diff the 7 fields: shipper, consignee, notify_party, port_of_loading, port_of_discharge, container_count, gross_weight_kg
3. null on either side → `NEEDS_REVIEW` + `missing_value`
4. Mismatches → `defect_fields`, `has_defect=true`, show `SI: X / BL: Y`
5. All match → "No mismatch detected", `has_defect=false`

---

## Known Dataset Traps (verified against data_v2)

| Trap | Evidence | Handling |
|------|----------|----------|
| Misleading subjects | email_004/052 "REQUEST BL DRAFT" subject but comparison body; 79/124 comparisons lack "CONFIRM DOCS" in subject | Body-intent signals, never subject keywords |
| Reply threads, no attachments | 43 RE_ + CONFIRM DOCS emails, 23 with zero attachments | Escalate on absence; can still classify as BL_COMPARISON by intent |
| Missing attachment | email_507 (SI only), email_495 (none) | `missing_attachment` review reason |
| Image-only scanned PDFs | email_512/513/514 (both docs) | Local GLM-OCR path |
| Corrupt PDFs | email_511_BL, email_515_BL ("no objects found") | try/except per file → `unreadable` review |
| Watermark decoy | "SCANNED COPY - NO OCR TEXT LAYER" in scan render | Ignore watermark text; typed scan content, extract normally |
| **Impostor document** | email_501_BL.txt is a COMMERCIAL INVOICE (name says BL) | Content-sniff title of every doc; non-SI/BL → `wrong_doc_type` |
| **Unrouted .docx** | 8 BL attachments are .docx (055, 097, 107, 291, 302, 354, 435, 462) | python-docx router branch |
| **Encoding trap** | email_519_SI.txt has unicode chars; win32 charmap default crashes | `open(..., encoding='utf-8', errors='replace')` everywhere |
| Multi-line field values | Addresses wrap + "ON BEHALF OF" chains (email_520) | Parser consumes continuation lines; compare company identity |
| Label synonym zoo | "Shipper/Exporter:", "NOTIFY PARTY:", "Notify:", "(POL):", "Discharge:" in BASE data | Alias table in text parser |
| Container count semantics | "6 x 40HC", possible "2x20GP + 3x40HC" | Normalize to total units; log raw string in evidence |
| Weight formats | "128.54 KG" vs "126,544 KGS", possible LBS | Strip commas, require KG; else `missing_value` review |
| Port identity | "PORT KLANG (WESTPORT), MALAYSIA (MYPKG)" vs "KLANG" | Normalize on UN/LOCODE 5-letter code when present |
| Silent submission default | scoring.py:46 scores missing emails as GENERAL | Assert len(submission)==520 before every submit |
| LLM output fragility | fenced/truncated/missing JSON | JSON-extraction regex + 1 retry + fallback NEEDS_REVIEW |
| Crash mid-run | API timeout/rate limit loses progress | Checkpoint results to disk per email; resumable |
| Escalation over-trigger | excessive NEEDS_REVIEW tanks escalation_precision | Tune 0.85 threshold on scoreboard submissions |

---

## Output Contract (per email, matches sample_submission.json)

```json
"email_042": {
  "category": "BL_COMPARISON",
  "status": "OK",                    // OK | MISMATCH | NEEDS_REVIEW
  "review_reason": null,             // wrong_doc_type | missing_attachment | unreadable | missing_value
  "defect_fields": ["container_count"],
  "has_defect": true
}
```

Internal additions beyond submission shape: `decided_by` (rule/sim/llm), `evidence` dict — kept locally for debugging/demo, stripped or harmless on submit.

---

## Build Order

0. `pip install python-docx openpyxl` + global utf-8 read helper (edge cases #3, #4)
1. Loader + signals + Stage 0 rules → submit → baseline score
2. Stage 1 evidence scoring + conflict detection → submit
3. Stage 2 TF-IDF similarity → submit
4. Stage 3 flash LLM classify for stragglers → submit
5. Extraction: .txt regex → .docx/.xlsx → .pdf text → submit (stage3 + end-to-end jump here)
6. Local GLM-OCR Docker for scanned PDFs → submit
7. Reliability polish: review queue with evidence, per-document fail isolation (try/except everywhere), retries, checkpointing
