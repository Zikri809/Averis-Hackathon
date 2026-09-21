# Stage 3 — Comparison

> Status: **DECIDED** (2026-09-19). Finalized architecture for the comparison stage.
> Upstream: `Stage 2 Extraction.md` (READY record pairs only). This stage produces the final submission fields.
> Problem-statement anchor: Capability 3 — *"Compare: check the values and surface any mismatched fields, showing the SI and BL values side by side."* — and the headline example: SI 3 containers / BL 4 → flag only container_count, show `SI: 3 / BL: 4`.

## Placement in the pipeline

```
Stage 2: EXTRACTION
        │  gate: only doc_status == READY record pairs (~110 emails)
        ▼
STAGE 3: COMPARISON  ← this stage
        │  emits: has_defect, defect_fields, side-by-side evidence
        ▼
Submission assembly (520 emails: Stage 1 categories + Stage 2 reviews + Stage 3 verdicts)
```

## What this stage is

Pure deterministic code (D6 — **never LLM**). Diff the two 7-field records, emit which fields differ. Reproducible, explainable, debuggable — every verdict traces to two values a human can eyeball.

It carries **0.50 of the final score** (end-to-end weight) despite being the smallest stage: e2e success requires category == BL_COMPARISON **AND** `has_defect` **AND** `defect_fields` matching ground truth **exactly** (`scoring.py:159`). One false-flagged field on an otherwise-correct email = zero e2e credit for that email. Precision on the field set is everything.

## Stage contract

**Inbound (per email, from Stage 2):**
```json
{"si_doc": {7 fields}, "bl_doc": {7 fields}, "evidence": {...}}
```

**Outbound:**
```json
{
  "has_defect": true,
  "defect_fields": ["container_count", "gross_weight_kg"],
  "diff_report": {"container_count": {"si": 6, "bl": 5},
                   "gross_weight_kg": {"si": 21577.0, "bl": 21577.0, ...}}
}
```
- `diff_report` is internal (demo artifact / review UI): the "SI: X / BL: Y" side-by-side the problem statement asks for.
- Non-READY emails never arrive here — Stage 2 exits them pre-escalated (missing_attachment / wrong_doc_type / unreadable / missing_value).

## Equality semantics per field (the one real design decision)

The scorer demands the exact defect-field set. Too strict → false alarms (stage3 precision + e2e loss); too loose → missed defects (stage3 recall + e2e loss). Empirically verified against all 46 defect emails and OK pairs:

| Field | Equality rule | Verified rationale (from data) |
|---|---|---|
| shipper / consignee / notify_party | normalize: uppercase → collapse whitespace → strip punctuation → **exact string equality** | Mutations are *entirely different companies* (e.g. SI "EAST BRIGHT FZ-LLC" vs BL "UAB NOVAKOPA") — no fuzzy matching needed; case/punct-insensitivity only absorbs formatting noise |
| port_of_loading / port_of_discharge | normalize: uppercase → strip punct → collapse ws → **exact equality on the name part** (LOCODE parenthetical removed before compare) | **Critical finding:** in all 16 txt port-defect pairs the LOCODE stays *identical* while the name mutates (SI `MOMBASA, KENYA (KEMBA)` vs BL `TUTICORIN, INDIA (KEMBA)`). The generator mutates only the name field, never `pod_code`. Comparing LOCODEs would miss 100% of port defects; comparing names catches all. LOCODE is kept as evidence only |
| container_count | **exact int equality** | Deltas are ±1, ±2 — no fuzz |
| gross_weight_kg | **exact numeric equality** after comma-strip | Deltas are ±500/±1000/±2000 — clean integers, no float tolerance needed; on OK pairs the raw weight strings were byte-identical (51/51 checked) |

Normalization pipeline (both sides, both field kinds): `upper() → strip punctuation → collapse whitespace` (alias tables for ports live in Stage 2's normalizer; comparison receives canonical values).

## Algorithm

```
defect_fields = []
for f in [shipper, consignee, notify_party, port_of_loading,
          port_of_discharge, container_count, gross_weight_kg]:
    si_v, bl_v = normalize(si_doc[f]), normalize(bl_doc[f])
    if si_v is None or bl_v is None:      # defensively — Stage 2 should have caught it
        exit to NEEDS_REVIEW/missing_value (never guess)
    if not equal(f, si_v, bl_v):
        defect_fields.append(f)
        diff_report[f] = {si: si_v, bl: bl_v}

has_defect = bool(defect_fields)
if not defect_fields: report = "No mismatch detected"
```

**ON BEHALF OF chains:** comparison's final say on "company identity" — Stage 2 supplies the first-line identity as the value; if equality fails on identity but the chain contains the counterpart (evidence), flag for review rather than defect (verified trap: email_520-style).

## Verified dataset facts this stage must handle

| Fact | Numbers | Implication |
|---|---|---|
| Defect email composition | 20 single-field, 26 two-field (46 total, all main set) | Two-field pairs are common — partial detection scores zero on e2e |
| Most-common defect combos | container_count ×5 alone; (container_count, port_of_discharge) ×4; (container_count, gross_weight_kg) ×4 | container_count is in ~59% of defect emails (19/32 txt+binary) |
| Defect field frequency | container_count 19, port_of_discharge 13, gross_weight_kg 12, notify_party 8, consignee 7, shipper 7, port_of_loading 6 | |
| Label synonymy on OK pairs | consignee label differs SI-vs-BL in ~53% of pairs (10/19 sampled) | Synonymy is Stage 2's job; by the time values reach Stage 3, labels are gone — only values diff |
| Same-value-different-format | 0 occurrences of differently-formatted identical weights on OK pairs | No fuzzy-tolerance arms race needed; clean equality is correct |

## Exit paths from this stage

| Outcome | Emitted | Goes to |
|---|---|---|
| All 7 equal | `has_defect=false, defect_fields=[]`, "No mismatch detected" | submission (status OK) |
| ≥1 differ | `has_defect=true, defect_fields=[...]` + diff_report | submission (status MISMATCH) |
| Defensive: null reached here | route back → `NEEDS_REVIEW/missing_value` | review queue (never a guess, D7) |

## Architectural properties

- **Pure function** — record pair in, verdict out; no I/O, no state, fully unit-testable
- **Determinism** (D6) — same input, same verdict, always; every flag traceable to two printed values
- **Zero cost** — no API, no GPU; 46 defect + ~64 clean emails diff in milliseconds
- **Evidence-first demo artifact** — diff_report doubles as the judge-facing "which email, what mismatched, SI vs BL side by side" report the problem statement asks for
- **Exact-set discipline** — defect_fields is emitted as the complete set, never partial; if any field's parse is doubtful, the email exits to review rather than emitting a wrong set (e2e is binary per email)

## Decision log (this stage)

| # | Decision | Rationale |
|---|---|---|
| C1 | Compare normalized *name parts* of ports, never LOCODE | LOCODE stays constant across defects (16/16 verified) — comparing it would miss every port defect |
| C2 | Exact numeric equality for weight/count; exact normalized string for parties/ports | Mutation deltas are large (±500 kg, ±1 ctr, whole-company swaps); fuzz only adds false alarms |
| C3 | Punctuation/case/whitespace-insensitive normalization before equality | Zero same-value-different-format cases in data, but formatting noise absorption is free insurance |
| C4 | Any null arriving at Stage 3 → escalate, never compare | D7; null-vs-value is not a diff, it's uncertainty |
| C5 | diff_report side-by-side emitted for every email (clean or not) | Problem statement's example report format; doubles as demo evidence |
| C6 | ON BEHALF OF identity mismatch w/ chain evidence → review, not defect | email_520 trap; identity ≠ textual inequality |
