# SDOC — Unified Architecture (v3)

> Status: **FINAL, supersedes** `SDOC_Comprehensive_Architecture_v2.pdf`, `Extend SDOC.pdf`,
> `DECISIONS.md`, and `Stage 1/2/3 *.md` where they conflict. Decision IDs (D/E/C) are kept
> for traceability; **v3-A\* / v3-B\* entries are corrections the adversarial review proved
> against `data_v2/`**. Scoring reference: `server/scoring.py` — stage1 0.30 / stage3 0.20 /
> **end-to-end 0.50** (verified `scoring.py:28`).

---

## 0. Verdict on the two new PDFs

| Document | Verdict | Why |
|---|---|---|
| **SDOC_Comprehensive_Architecture_v2.pdf** | **Adopt as the base, with corrections** | It correctly merges the three decided stages and adds a bounded LLM label fallback, per-field confidence, review queue + alias learning, auto-draft clarification email, deployment layout, demo script, and time budget. But it silently rewrites the decided Stage-2 escape hatch, contains wrong worked examples, and carries forward three score-relevant defects as if verified. |
| **Extend SDOC.pdf** | **Fully absorbed** | It is the proposal that v2 was built from. Its additions (confidence flag, bounded fallback, alias learning, auto-draft email, Docker layout, demo script, time budget) are all present in v2 and are carried into v3 with guardrails. Its two exclusions (no fuzzy compare, no LLM-first classify) are confirmed correct and kept. |

**Bottom line: the two PDFs fit the original plan well as *product* extensions, but two of the
"verified" numbers they inherit are wrong and three latent defects they restate would cost
~0.17 of the final score if implemented literally. All are fixed in v3.**

---

## 1. Verified corrections register

Every item below was reproduced against `data_v2/` during adversarial review. "Blast radius"
= score lost if implemented literally and never fixed.

### v3-A1 — CRITICAL — zero-attachment rule (blast radius ~0.042)

- **Wrong (v2 §2.4, `Stage 2 Extraction.md:56`, `DECISIONS.md:144`):** "0 attachments, or SI only" → `missing_attachment`.
- **Reality:** 94 BL_COMPARISON emails have zero attachments; **91 of them are ground-truth OK**, 3 are NEEDS_REVIEW. The 3 real cases (506/508/510) are distinguished by body phrasing (`dropped` / `still missing`). 507/509 (SI-only) are genuine.
- **Correct rule (v3 gate):**
  ```
  category == BL_COMPARISON is a category-only decision, never an attachment decision.
  Extraction outcome:
    0 attachments  AND body matches /dropped|still missing/i  → NEEDS_REVIEW/missing_attachment
    1 attachment   (SI only, 507/509)                          → NEEDS_REVIEW/missing_attachment
    2 attachments  → parse
  ```
- **Impact if wrong:** escalating all zero-attachment BLs → `escalation_precision` = 0.18; routing them away from BL_COMPARISON → stage1 macro-F1 1.0 → 0.8553, final 0.9987 → **0.9566**.

### v3-A2 — CRITICAL — unit rule breaks binary formats (blast radius ~0.098)

- **Wrong (v2 §2.9):** "gross_weight_kg: strip commas, **require KG/KGS on the line** → float."
- **Reality:** `.xlsx` weight cells are raw numbers with label `GROSS WEIGHT` and no unit (verified `email_005_SI` B10 = `341715`); `.docx` weight cells are written `f"{weight:,}"` — no unit by construction. 11 xlsx rows across 15 emails carry no `kg/kgs`.
- **Correct rule (v3):** require a KG/KGS marker only for `.txt`/`.pdf`/OCR text. For `.xlsx`/`.docx` **cell-typed numeric values, accept the number as KG without a unit token**. Never guess a unit from a string value.
- **Impact if wrong:** 9 gold-MISMATCH xlsx/docx emails lose e2e credit = **0.0978**.

### v3-A3 — HIGH — CJK label normalization is wrong (blast radius ~0.033 + 51 files)

- **Wrong (v2 §2.8):** "`Gross Weight 毛重(KGS)` → `GROSS WEIGHT`" and "strip parentheticals `(...)` and `（...）`".
- **Reality:** the generator label is `Gross Weight毛重(KGS)` (**no space**). v2's own normalization yields `GROSS WEIGHT毛重` (CJK survives, half-width parens only). Also verified in PDFs: `TOTAL Gross WeightII(KGS)` mojibake in 4 pairs, 2 of which (`email_313`, `email_351`) are MISMATCH with `gross_weight_kg` defective.
- **Correct rule (v3):** normalize by stripping **all non-ASCII** (`re.sub(r'[^\x00-\x7F]', '', s)`) before punctuation collapse; match `TOTAL GROSS WEIGHT` / `GROSS WEIGHT` as a **prefix on the TOTAL line**, never as a container-table column header.

### v3-A4 — HIGH — "longest-alias-first" vs "match exact" is self-contradictory (v2 §2.8)

- **Correct rule (v3):** normalize the full label, then **exact-match** against the alias table, iterating aliases **longest-first** as a tiebreak only. Containment/substring matching is forbidden — it is the only way `Notify Party/Intermediate Consignee` can be routed into `consignee`.

### v3-A5 — HIGH — port equality rule undefined for binary formats (blast radius ~0.022)

- **Wrong (v2 §3.4):** "in all 16 txt port-defect pairs the LOCODE stays identical" — actually 15 pairs / 16 field instances; and `email_243` (xlsx) and `email_434` (pdf) have **no LOCODE at all**.
- **Correct rule (v3):** compare **normalized name parts only** (strip a trailing `([A-Z]{5})` if present; strip `(WESTPORT)`-style qualifiers for comparison but keep them in evidence). Never compare LOCODEs. Verified: 16/16 txt instances keep the code while the name mutates; 0 counterexamples on OK pairs.

### v3-A6 — MEDIUM — inventory and example numbers corrected

| v2 claim | Verified v3 value |
|---|---|
| `.txt ~78%` | 192/250 = **76.8%** |
| `.xlsx 13 pairs` (14 ids listed) | **15 emails** carry `.xlsx` (22 files: 7 xlsx+xlsx, 8 xlsx+docx); v2's list omits `email_435` |
| `.pdf (text layer) 10 pairs` | 13 pdf+pdf + **2 pdf+txt** = 28 pdf files |
| `no attachment 5` | 5 edge cases **plus 94 zero-attachment BL emails (91 OK)** |
| §3.3 example `gross_weight_kg si 21577.0 == bl 21577.0` in `defect_fields` | broken example; `si:6/bl:5` matches no email. Replace with a real case, e.g. `email_313` (container_count + gross_weight_kg, pdf) |
| §2.3 example record | it is `email_520_SI` — a NEEDS_REVIEW case with a blank consignee; must never appear as a READY example |
| §1.7 / v2 `email_495` as missing-attachment | `email_495` is **OK**, no attachments; only 506/508/510 + 507/509 are missing_attachment |
| §3.6 "container_count ~59% of defect emails (19/32)" | 19/46 = **41.3%**; partition is 33 txt-only / 13 binary |
| §3.4 "Mutations are entirely different companies" | **4/16** party defects are prefix/first-token related (`email_145`, `email_256`, …). Exact equality still catches all; the premise is wrong, the rule survives |
| §3.4 "0 same-value-different-format on OK pairs" | true for `.txt` (51/51 byte-identical); **2 counterexamples** in binaries (`email_055`, `email_462`: `243588` vs `243,588`). Numeric values never differ |
| §3.6 "~125 of 520 gate" | ground truth BL_COMPARISON = **220**; 124 have two docs, 94 none, 2 SI-only. The gate is a **category** gate |
| §1.7 / `DECISIONS.md:18` "escalation_f1 is a scored metric" | `scoring.py:175-177` — reliability is returned but **never weighted**. Escalation still matters via e2e (false escalation = lost e2e), but not as a weighted axis |

### v3-A7 — Decision-log deltas to record explicitly

| Old | v3 |
|---|---|
| D6 rationale ("`escalation_f1` is a scored metric") | Corrected: reliability is diagnostic-only; e2e is the only axis an escalation can move |
| `Stage 2 Extraction.md` E5 (scans stay `unreadable`) | **Kept** — OCR is demo evidence only and never changes a submission field |
| v2 §2.10 ("no LLM in this stage's main path") | Kept as a *main-path* guarantee: the bounded fallback is demo-flag-only, never on the frozen scored run (see §4.3) |

---

## 2. The unified pipeline (authoritative)

```
520 emails (inbox/*.json)
        │
        ▼
STAGE 1 — CLASSIFICATION  (metadata only; D3)
  signals → hard rules → weighted evidence → TF-IDF similarity → GLM flash (5-shot, temp 0)
  emits: category ∈ {BL_COMPARISON, SI_REQUEST, INVOICE_QUERY, GENERAL, SPAM}
         decided_by ∈ {rule, sim, llm}   (optional in payload; feeds rule_pct)
        │
        ▼  gate: category == BL_COMPARISON   →  220 emails (verified)
        │
STAGE 2 — EXTRACTION  (attachments only; E1)
  router(.txt/.xlsx/.docx/.pdf) → doc-type sniff → alias table → typed normalizers
  gate: 0-att + dropped/still-missing → missing_attachment
        1-att (SI only)               → missing_attachment
        2-att                         → parse
  emits: {si_doc, bl_doc, doc_status, review_reason, evidence[+confidence]}
        │
        ▼  gate: doc_status == READY   →  109 main-set pairs
        │
STAGE 3 — COMPARISON  (deterministic, D6 — never LLM)
  normalize → exact equality per field → defect_fields (complete set) + diff_report
        │
        ▼
SUBMISSION ASSEMBLY  (520 keys, assert before submit)
        │
        ├─▶ Review queue (escalations, human resolution)
        ├─▶ Alias learning (reviewer-confirmed, append-only, OFF during scored run)
        └─▶ Auto-draft clarification email (draft-only, .eml outbox, never sent)
```

**Scored-run discipline:** the frozen submission run is deterministic and offline. Every v3
extension is either display-only or behind `SCORED_RUN=1` (which disables LLM label fallback,
learned aliases, and OCR).

### 2.1 Stage 1 — Classification (unchanged core, corrected rationale)

- Cascade: hard rules → weighted evidence → TF-IDF → flash LLM, exactly as decided (D1–D4).
- **v3 correction:** the ~85–90% free-resolution figure must be **measured**, not assumed. 94 of 220 BL emails have zero attachments and no `has_SI`/`has_BL` signal — they must be caught by body-intent (`intent_check`) or the LLM. Track the real `decided_by` mix on the first run.
- All traps and prompt contracts unchanged (`Stage 1 Classification.md`).

### 2.2 Stage 2 — Extraction (three fixes + one bounded side-door)

Core 4 sub-components unchanged: Router → DocType sniff → Parser (shared alias table) →
Normalizers. Fixes applied: **v3-A2** (unit rule), **v3-A3** (non-ASCII strip), **v3-A4** (exact-match).

- Alias table remains **data, not code** (E2), generated from `pools.py:175-188` — but see the v3 normalization fix, the generator label is `Gross Weight毛重(KGS)` with no space.
- PDF trap: anchor **count** on the `No. of Containers:` summary line; anchor **weight** on the `TOTAL` line (prefix match, ASCII-normalized); ignore container-table column headers.
- `null` = genuinely absent; `readable:false` = parse failure (E3, kept).
- Per-file try/except isolation (E7, kept); checkpoint per email, append-only, idempotent on resume.

### 2.3 Stage 3 — Comparison (unchanged, D6)

Pure deterministic diff of the 7 canonical fields. Equality semantics per `Stage 3 Comparison.md`
(parties exact-normalized; ports name-only; count int; weight numeric). `defect_fields` is the
**complete set or nothing** — a doubtful field exits to review, because e2e is binary per email
(`scoring.py:159` exact-set match). `diff_report` emitted for every email as the judge-facing
side-by-side.

### 2.4 Exit statuses (authoritative)

| doc_status | review_reason | Trigger |
|---|---|---|
| READY | null | 2 attachments parsed, 7 fields present |
| NEEDS_REVIEW | `missing_attachment` | 0 att + dropped/still-missing body, or SI-only |
| NEEDS_REVIEW | `wrong_doc_type` | content-sniff finds Commercial Invoice / Packing List / COO |
| NEEDS_REVIEW | `unreadable` | corrupt/empty file or no text layer (511_BL, 515_BL, 512–514) |
| NEEDS_REVIEW | `missing_value` | parsed but ≥1 required field blank (`???`/`TBA`/`____`/`N/A`) |

---

## 3. v2 additions — adjudicated verdicts

| Addition | Verdict | Binding guardrail |
|---|---|---|
| **Review queue** (v2 §4) | **ADOPT** | One row per escalation: email_id, reason, raw label, snippet, confidence, file link. Resolution: confirm value / correct value / confirm escalation. UI is display-only — **never reads ground truth**; no auth needed because it writes only the proposal file. |
| **Alias learning** (v2 §4) | **ADOPT-WITH-GUARDRAIL** | Append-only JSONL (`state/alias_learned.jsonl`), host-mounted, **human-confirmed only**. Precedence: generator table **>** learned. Learned aliases are **disabled when `SCORED_RUN=1`**. Validate: reject if normalized label collides with a different canonical field or is a substring of / contains an existing alias. Atomic write (`os.replace` + lock). Learned-file hash enters the checkpoint key so a re-run re-parses. |
| **Per-field confidence** (v2 §2.6.2) | **ADOPT-WITH-GUARDRAIL** | Define the scale once: `1.0` alias match, `0.5` conflict-resolved (prefer-non-blank), LLM score when fallback fired. **Strictly display-only** — assert no Stage-2/3 branch reads it. Delete the OCR-confidence bullet (unreachable under E5). |
| **Bounded LLM label fallback** (v2 §2.6.1) | **ADOPT AS DEMO-ONLY** | Trigger only on a label whose *value* is type-compatible with one of the 7 fields (port/party/weight/count) and whose field is currently null — never on `NET WEIGHT`, `Export Carrier`, `Freight`, `HS Code`, etc. Accept at ≥0.90. **Disabled when `SCORED_RUN=1`.** One call per unmatched label, cached, timeout→`missing_value`. The decided doc-level escape hatch (whole-doc LLM) stays documented but unbuilt. |
| **Auto-draft clarification email** (v2 §5) | **ADOPT-WITH-GUARDRAIL** | **Draft-only. No SMTP client in the repo.** Write `outbox/{email_id}.eml` + UI preview with a "DRAFT — NOT SENT" banner. Only for `status == MISMATCH` with non-empty `diff_report`; never for NEEDS_REVIEW. Recipient = `From:` of the BL-carrying email, verbatim. `{ref}` is extracted from the attachment's `Booking Ref` label (new data — v2's "no new data" claim is false); if absent, omit the line. |
| **Deployment layout** (v2 §6) | **ADOPT-WITH-CORRECTIONS** | Consume the organizers' shipped `inbox` service — do **not** re-declare or duplicate it. Inside the compose network the app reaches `http://inbox:8000`; from the host it is `http://localhost:8080`. Add parser deps (`python-docx`, `openpyxl`, `pymupdf`) to the app image. Never set `REVEAL_GT=1` during the demo. No `worker` container. State on a host-mounted `./state` volume. |
| **Demo script** (v2 §7) | **ADOPT-WITH-CORRECTIONS** | Step 3 must not use fabricated "unseen" labels — `POL` and `Load Port` are already in the alias table and `Loading Port`/`Origin Port` occur 0 times. Replace with a **`NET WEIGHT` negative control** (real data, 5 files): show the extractor declining to map an unmatched label with the threshold visible. Step 4 uses a pre-seeded review case. Step 6 is the frozen run with a 520-key assert. |
| **Time budget** (v2 §8) | **ADOPT-WITH-REORDER** | Gate: no v2 extension work until a `/submit` shows stage1 ≥0.95, stage3 ≥0.95, e2e ≥0.95. See §5. |
| **Exclusions** (v2 §9) | **CONFIRMED, extended** | No fuzzy comparison, no LLM-first classification — both correct. See §7 for additions. |

---

## 4. Submission & deployment contract (corrected against the real harness)

- **Endpoint:** `POST /submit` on the organizers' `inbox` service. Body = **flat JSON with all 520 keys**, each `{category, status, review_reason, has_defect, defect_fields}` (`sample_submission.json`, verified 520 keys). `decided_by` is optional and only feeds `rule_pct`.
- **Silent trap (verified):** missing keys default to `GENERAL` server-side (`scoring.py:46`) and the endpoint still returns HTTP 200. A partial submission is silently penalized.
- **Preflight (run before every submit, in order):**
  1. `GET /health` → `{"status":"ok","emails":520,"scoring_available":true}`; if `scoring_available` is false the `/secrets` mount is missing → do not submit.
  2. `assert len(sub) == 520` and `set(sub) == set(email_ids)`.
  3. Assert every `category ∈ scoring.CATEGORIES`, every `review_reason ∈ scoring.REVIEW_REASONS ∪ {None}`, `has_defect == (status == "MISMATCH")`.
  4. Dry-run `POST /submit` with `sample_submission.json` (expect final ≈ 0.0124) to prove the pipe.
  5. Real submit → assert returned `n_emails == 520` before believing `final_score`.
  6. `docker compose down && up` → re-run step 4 to prove state survives (or is correctly absent).
- **Env:** document `DATA_DIR`, `GROUND_TRUTH`, `REVEAL_GT`, `JUDGE_TOKEN`. `REVEAL_GT=1` must always be paired with `JUDGE_TOKEN`; default is 404.

---

## 5. Build order and time budget (re-ordered, gate-enforced)

**Tier 0 — floor, must ship first (~4–5 h, target first submit within the first 90 min):**

| # | Step | Why first |
|---|---|---|
| 0 | Env setup + `Inbox("data_v2")` smoke test + 520-key submission assembly + first `/submit` (baseline 0.0124) | Proves the entire deployment/score path for free |
| 1 | Router + `.txt` parser + alias table (192/250 files; **33 of 46 defects**) + harness | txt core alone ≈ 0.83 of the score |
| 2 | Stage 1 cascade (rules + evidence; LLM last) | 0.30 weight; submit → ~0.30 |
| 3 | Stage 3 comparison on txt pairs | e2e jump; submit |
| 4 | **Submit again — minimum viable, judge-credible demo** |  |

**Tier 1 — with ≥3 h remaining:** `.xlsx`/`.docx` parsers (v3-A2 fix mandatory) → `.pdf`
text-layer path (v3-A3 fix mandatory) → doc-type sniff + blank/corrupt exits. Worth ~0.11 combined.

**Tier 2 — cut first, in this order:** OCR/GPU (zero score, highest infra risk — keep only the
detection → `unreadable`) → review UI (static JSON dump is acceptable) → alias-learning
persistence (hand-edited JSON acceptable) → auto-draft email (outbox file only).

**Never cut:** the 520-key assert, the checkpoint file, the pre-submit dry run, the rehearsal.
Add a **2 h integration/debug buffer**; the v2 budget's 11–14.5 h had none. Protect a
**1 h demo block** — do not let it be "remaining time."

---

## 6. Demo script (corrected)

1. Live triage with `decided_by` visible (pre-render from a cached run; keep an `--offline` flag).
2. Open a real two-field case: `email_313` (pdf, `container_count` + `gross_weight_kg`) or `email_097` (xlsx/docx) — side-by-side `diff_report` with confidence highlights.
3. **Negative control:** show `NET WEIGHT` (real, 5 files) being correctly *declined* by the bounded fallback, threshold visible. (Optionally, a synthetic `Loading Port:` attachment clearly labelled "synthetic stress input".)
4. Pre-seeded NEEDS_REVIEW case → resolve live → show the learned-alias JSONL gain the entry.
5. Auto-drafted `.eml` preview for a real MISMATCH — "DRAFT — NOT SENT".
6. Frozen run → `POST /submit` → scoreboard, after the 520-key assert.

Steps 3 and 5 are the "wow" beats; both must have a recorded fallback in case of network/GPU failure.

---

## 7. Explicitly out of scope

**Kept from v2:** fuzzy/similarity comparison (verified harmful: e2e is binary, exact equality
catches every real defect — including the 4 prefix-related party mutations); LLM-first
classification (cascade resolves the bulk free at near-100% rule precision).

**Added by v3 adversarial review:**

1. **Real email sending** — no SMTP, no credentials, no mailto auto-trigger. Draft `.eml` only.
2. **Ground-truth leakage into the review UI** — the queue must never read `ground_truth.json`, even behind flags, during a live demo.
3. **Multi-user review / auth** — single reviewer, no identity, no audit trail beyond the JSONL timestamp.
4. **OCR in the critical path** — scans exit `unreadable` by decision (E5); OCR text is demo evidence only and must not alter a submission field.
5. **Persistence/concurrency beyond a single writer** — append-only JSONL + file lock + `os.replace`; no Postgres/Redis/Celery.
6. **Frozen-run ambiguity** — the final submission must come from a run with `SCORED_RUN=1` (fallback + learned aliases + OCR disabled) and the alias/checkpoint hashes recorded.

---

## 8. Adversarial review log (provenance)

| Reviewer | Scope | Key outcome |
|---|---|---|
| Data verifier | 12 dataset claims vs `data_v2/` | Verified counts (220/125/75/60/40; 46 defects; 20 NEEDS_REVIEW), falsified the xlsx inventory, the "0 same-value-different-format" claim, and the ~125 gate reading |
| Adversarial architecture reviewer | v2 vs D/E/C decisions + internal consistency | Found the silent D6 escape-hatch rewrite, the broken §3.3 example, the unreachable confidence path, the stale-checkpoint × alias-learning bug, and ranked the untested claims by blast radius |
| Ops/demo red team | §§4–8 vs the real harness | Found the false demo premise (no unseen labels), the `data-server:8080` mismatch, the silent partial-submission trap, the auto-send hazard, and the alias-poisoning path |
| Independent spot-check (this session) | A1/A2/A3/A5 + zero-attachment rule | Reproduced: 94 zero-att BL (91 OK), unitless xlsx/docx weights, `Gross Weight毛重(KGS)` raw label, `Gross WeightII(KGS)` mojibake, 15 pairs/16 instances of LOCODE-identical port defects, 13 binary MISMATCH emails |

**Score-impact reference (computed from ground truth):**

| Scenario | final |
|---|---|
| Perfect | 1.0000 |
| Classification only | 0.3000 |
| All-GENERAL baseline | 0.0124 |
| txt core perfect; binaries escalated | 0.8258 |
| All port defects missed | 0.6470 |
| Literal v2 unit rule (A2) | −0.0978 |
| Literal v2 zero-attachment rule (A1) | −0.042 |
| Literal v2 CJK normalization (A3) | −0.033 |

The three v2 defects together outweigh every v2 extension's score contribution (which is zero —
they move rubric lines, not `final_score`). **Fix A1–A3 before building any extension.**
