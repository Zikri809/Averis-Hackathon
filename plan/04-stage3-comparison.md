# Plan 04 — Stage 3: Comparison (owner: Comparison agent)

> Scope: pure deterministic diff of two 7-field `DocRecord`s. **Never LLM** (D6).
> Carries 0.50 of the score; one false-flagged field zeroes an email's e2e credit
> (`scoring.py:159` exact-set match). This is the smallest plan and the strictest.

## Deliverable

`Verdict` with the complete `defect_fields` set and `diff_report` for every READY pair; zero
false positives on the 51 txt-only OK pairs at W2 and all 63 OK pairs at W3; all 46 defects
exactly matched by W3.

## Files owned

| File | Purpose |
|---|---|
| `app/stage3_compare.py` | The diff algorithm + exit routing |
| `app/stage3_normalize.py` | Comparison-side normalization (uses Foundation `normalize.norm_compare`) |

## Contracts

**Inbound:** `{"si_doc": DocRecord, "bl_doc": DocRecord}` (READY only).
**Outbound:** `Verdict` per `schema.py`.

## Equality semantics (authoritative — verified in v3)

| Field | Rule |
|---|---|
| shipper / consignee / notify_party | `norm_compare` (uppercase → strip punct → collapse ws) → **exact string equality** |
| port_of_loading / port_of_discharge | strip a trailing `([A-Z]{5})` code if present, strip qualifiers for compare, **compare name part only**, exact equality; never compare LOCODEs |
| container_count | exact int equality |
| gross_weight_kg | exact float equality (both sides already normalized to KG by Stage 2) |
| any side `None` | **never a diff** → exit `NEEDS_REVIEW/missing_value` (C4) |

**ON BEHALF OF guard (C6) — literal token required:** if party identity mismatches but **one side's
raw evidence contains the literal string `ON BEHALF OF`** and the counterpart identity appears in
that same chain → escalate to review, do not flag a defect. The guard must NOT fire on mere
prefix/substring similarity: verified false-positive risk on `email_145`, `email_256`, `email_312`,
`email_379` (`APRIL FINE PAPER TRADING` vs `APRIL FINE PAPER TRADING (MIDDLE EAST) FZE` etc.) —
these are genuine defects and must be flagged. 56 files contain an `ON BEHALF OF` chain; the guard
only applies when identity equality fails *and* the literal token is present.

## Tasks

| # | Task | Verification |
|---|---|---|
| S1 | `compare(si_doc, bl_doc) -> Verdict` pure function; null guard → escalation signal | `pytest tests/test_compare.py` unit matrix |
| S2 | Port name normalization: strip code parenthetical, strip `(WESTPORT)`-style qualifier for compare only, keep full raw in `diff_report` | 15 pairs / 16 instances: all flagged; 0 OK pairs flagged |
| S3 | Party equality on normalized identity; literal-token `ON BEHALF OF` guard | 4 prefix-related party defects (`email_145`, `email_256`, `email_312`, `email_379`) still flagged; 520 exits review not defect |
| S4 | Count/weight exact equality | all 19 count defects + 12 weight defects flagged; zero OK false positives |
| S5 | `diff_report` emitted for every email (clean and defective) — judge-facing artifact | all 109 pairs have a report |
| S6 | Exit routing: all-equal → OK; ≥1 diff → MISMATCH; null → NEEDS_REVIEW/missing_value | W2: 33 txt defects + 51 txt-only OK exact; W3: 46 defects + 63 OK total |

## Edge cases owned here

| Case | Rule |
|---|---|
| Null reached comparison (Stage 2 bug) | escalate, never compare (defensive) |
| Port defect where LOCODE identical, name differs (16 instances) | must flag via name |
| Port values with no LOCODE (243, 434) | compare names as-is; no code logic |
| Party prefix mutation (`APRIL FINE PAPER TRADING` → `… (MIDDLE EAST) FZE`) | exact equality flags it; ON BEHALF OF guard must **not** fire (145/256/312/379) |
| Whole-company swap (004: `EAST BRIGHT FZ-LLC` → `UAB NOVAKOPA`) | flags |
| `ON BEHALF OF` chain (520 shape + 55 files) | review, not defect — only with the literal token |
| Two-field defects (26 emails) | complete set emitted, never partial |
| Whitespace/punctuation noise | normalized away; zero same-value-different-format in txt data |
| Count `15 x 20'GP` → 15 | int equality, never string |
| Weight `243,588` vs `243588` | numeric equality (formatting absorbed by Stage 2) |
| Both sides null | escalation, not "equal" |
| Binary OK pairs (055, 208, 411, 462) | zero false defect fields — regression guard for parser fixes |

## Tests

- `test_compare.py` — truth table for every field type: equal / differ / null.
- `test_compare_real.py` — run over READY pairs (from fixture extracted records):
  **W2: 33 txt defects + 51 txt-only OK pairs** (binary pairs are stubbed `unreadable` at W2);
  **W3: all 46 defects + 63 OK pairs**. Assert `defect_fields` == GT and zero false flags on OK pairs.
- `test_port_semantics.py` — LOCODE-identical pairs; no-LOCODE pairs; qualifier stripping.
- `test_on_behalf_of.py` — 520-shaped record → review path; 145/256/312/379 → defect (guard must not fire).

## Definition of done

**W2 gate (txt core):**
1. `tools/verify_comparison.py --scope txt` → 33/33 txt defects exact; zero false positives on the 51 txt-only OK pairs.
2. `pytest tests/test_compare*.py -q` green.
3. No import of any LLM/network module in `stage3_*.py` (grep assertion in test).

**W3 gate (full):**
4. `tools/verify_comparison.py` → e2e success 46/46; stage3 defect-F1 ≥ 0.95.
5. Field-level precision = 1.0 across all OK pairs (including binary OK pairs 055/208/411/462).

## Dependencies

- Imports: `schema`, `normalize` (Foundation) only.
- Consumed by: `run.py`; the Extensions agent reads `diff_report` (read-only) for draft emails.
- S6's full verification is W3-scoped; the W2-scoped subset (txt) is defined above.
