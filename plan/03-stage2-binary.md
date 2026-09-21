# Plan 03 — Stage 2: Binary Extraction (owner: Binary extraction agent)

> Scope: `.xlsx`, `.docx`, `.pdf` (text layer + image-only + corrupt) parsers and the shared
> doc-type sniff. 13 of 46 defect emails are binary (worth ~0.28 e2e). The three v3 corrections
> that live here (A2 unit rule, A3 PDF mojibake, A5 port name rule) are **mandatory**.

## Deliverable

All 250 attachments route to a parser; every binary defect email produces the exact
`defect_fields`; scans/corrupt files exit `unreadable` without crashing the run.

## Files owned

| File | Purpose |
|---|---|
| `app/stage2/xlsx_parser.py` | openpyxl label/value extraction |
| `app/stage2/docx_parser.py` | python-docx table extraction |
| `app/stage2/pdf_parser.py` | pymupdf text layer + image-only detection + corrupt handling |
| `app/stage2/doctype.py` | shared doc-type sniff (called by router for all formats) |
| `app/stage2/binary_parsers.py` | `register_all(router)` entry point for the Foundation orchestrator |
| `tests/test_xlsx_parser.py`, `tests/test_docx_parser.py`, `tests/test_pdf_parser.py`, `tests/test_binary_failures.py`, `tests/test_doctype.py` | Unit tests |

## Contracts

Same `DocRecord` as `02-stage2-text.md`. The Binary agent exposes one function that the Foundation
orchestrator calls; it never edits `router.py`:

```python
# app/stage2/binary_parsers.py (Binary agent) — invoked by run.py (Foundation)
def register_all(router):
    router.register(".xlsx", parse_xlsx)
    router.register(".docx", parse_docx)
    router.register(".pdf",  parse_pdf)
```

## Format-specific extraction rules (verified against `render.py` and the real files)

| Format | Rule | Evidence |
|---|---|---|
| `.xlsx` | col A = label, col B = value; **require an alias hit to accept a row** (rejects `BL INSTRUCTION`/so_number/noise rows); weight cell is a **raw number, no unit** → accept as KG (v3-A2); party values are `"NAME \| addr1; addr2"` in one cell → **split on `" \| "`, first part = identity** | `render.py:176-193`; 005_SI, 243_SI, 243_BL (CJK label) |
| `.docx` | table rows: cell[0] label (may carry `(发货人)` suffix), cell[1] value with `name\naddr\naddr` → **first non-empty line = identity**; weight is `f"{weight:,}"` **no unit** → accept as KG (v3-A2) | `render.py:142-165`; 055_BL |
| `.pdf` text layer | pair spans **within the same `line` object** (pymupdf), tolerance ≈2pt on baseline y; value = spans right of the label; **count** anchored to the `No. of Containers`/`Total Containers`/`Container Count` summary line; **weight** anchored to a line whose joined spans start with `TOTAL` + a `GROSS WEIGHT`-ish prefix | `render.py:92-134`; 313_BL, 434_BL |
| `.pdf` image-only | `page.get_text()` empty + embedded image present → `unreadable` (E5; OCR is demo-only, never in scored run) | 512, 513, 514 |
| `.pdf` corrupt | pymupdf raises → per-file try/except → `readable:false` → `unreadable`; sibling unaffected | 511_BL, 515_BL |

**PDF pairing facts (measured):** label/value baselines differ by 0.1–0.2pt on most fields and 1.7pt
on the mojibake span — exact equality fails, use ~2pt tolerance. The `TOTAL` line is a single line
object with three spans (`TOTAL Gross Weight` + `II` + `(KGS): 117,770 KG`) — **join spans in the
line before matching**. The `II` is ASCII, so the fix is prefix-matching on the joined line, not
ASCII-stripping alone. The container-table header `GROSS WEIGHT (KG)` has no value span to its
right; **never fall back to "next span below"** — that grabs the first container weight and
creates false defects on every PDF.

## Tasks

| # | Task | Verification |
|---|---|---|
| B1 | `doctype.py`: first-line/sheet-title/text-layer sniff → SI / BL / IMPOSTOR; **starts immediately (not blocked by aliases)** | 501–505 impostor; 055/097/107/291/302/354/435/462 docx BLs identified |
| B2 | `xlsx_parser.py`: alias-hit row filter, raw-int weight, `" \| "` party split, CJK label path | 15 xlsx emails parse; `email_005_SI` B10=341715 → 341715.0 kg; 243_BL weight extracted |
| B3 | `docx_parser.py`: bilingual label suffix strip, first-line identity, comma weight | 8 docx BLs parse; `email_055_BL` weight `243,588` → 243588.0 |
| B4 | `pdf_parser.py`: same-line span pairing with 2pt tolerance, count/weight anchors | 13 pdf+pdf + 2 pdf+txt parse; 434's port value extracted |
| B5 | PDF mojibake: join line spans, prefix-match `TOTAL GROSS WEIGHT` (ASCII `II` included) | **8 files / 6 emails**: 160_SI, 208_SI, 208_BL, 273_BL, 313_BL, 351_SI, 411_SI, 411_BL — incl. OK pairs 208/411 with **no false defect** |
| B6 | Image-only + corrupt detection paths; **starts immediately** | 511/515 unreadable; 512–514 unreadable |
| B7 | Port values without LOCODE (243 xlsx `PORT KLANG (WESTPORT), MALAYSIA`; 434 pdf) | name extracted; no code assumed |

## Edge cases owned here

| Case | Rule |
|---|---|
| Unitless weight in binary (v3-A2) | numeric cell/paragraph value is KG by construction; never `null` for missing unit token |
| **CJK label on xlsx** (`Gross Weight毛重(KGS)` in 243_BL, 171_SI, 496_BL) | shared alias normalizer strips non-ASCII → weight extracted; otherwise false `missing_value` on 243 loses a gold defect |
| **Party separator asymmetry** | xlsx cell `"NAME \| addr1; addr2"` → split on `" \| "`; docx cell `"NAME\naddr1\naddr2"` → first line. Using whole-cell for xlsx creates a false shipper defect on OK pair 055/462 |
| `GROSS WEIGHT (KG)` column header vs `TOTAL` line (PDF) | anchor weight on TOTAL only; **no "next span below" fallback** — it would grab a container weight and create false defects on all PDFs |
| `Gross WeightII(KGS)` mojibake (8 files / 6 emails) | join line spans, ASCII-normalize, prefix-match `TOTAL GROSS WEIGHT`; OK pairs 208/411 must stay OK |
| Bilingual docx labels `Shipper (发货人)` | strip parentheticals incl. CJK before alias lookup |
| xlsx noise rows | require an alias hit; `BL INSTRUCTION`/so_number rows rejected |
| PDF label and value on separate lines | not present in data (434 differs by 0.1pt only); if ever encountered → label without value → field `null`, never guess |
| Multi-page PDF | iterate all pages; merge label hits; prefer TOTAL/summary hits |
| Empty/corrupt file | zero-byte check first, then parser try/except → `readable:false` |
| Encrypted PDF | treat as `unreadable` |
| Unknown extension | router returns `unreadable` with note `unsupported format` |
| Watermark drawn into image (512–514) | no text layer → `unreadable`, no sniff attempt |

## Tests

- `test_doctype.py` — all formats' titles; impostors 501–505; sheet titles `S.I.`/`BL`.
- `test_xlsx_parser.py` — 005, 097, 243 (CJK label + no LOCODE port), 462, 481, 496; assert 055/462 parties equal.
- `test_docx_parser.py` — 055, 302, 354, 435; bilingual labels; comma weight.
- `test_pdf_parser.py` — 059, 160, 208, 273, 313, 351, 411, 434, 499; mojibake; header-vs-TOTAL trap; assert 208/411 OK pairs show no weight diff.
- `test_binary_failures.py` — 511_BL, 515_BL corrupt; 512–514 image-only; zero-byte synthetic; encrypted synthetic.

## Definition of done (W3 gate)

1. `tools/verify_extraction.py --scope all` → zero parser bugs (agreement structure == GT).
2. All 13 binary defect emails have exact `defect_fields` extractable (see `06-verification.md` §2).
3. 511/515 → `unreadable`; 512–514 → `unreadable`; sibling docs unaffected.
4. `pytest tests/test_*parser*.py tests/test_doctype.py -q` green.
5. No unit-based null for any binary weight (grep test: zero `missing_value` escalations caused by missing `KG` token).
6. OK pairs with binary sides (055, 208, 411, 462, …) show **zero** false defect fields.

## Dependencies

- Imports: `schema`, `normalize`, `state` (Foundation), `aliases` (Text agent).
- **B1 (`doctype.py`) and B6 (failure paths) start immediately** — they do not need the alias table.
  B2–B5, B7 are blocked only until `aliases.py` (02 T1) lands, **not** until the full W2 gate;
  this matches README's rule ("no B2–B5/B7 before `aliases.py`").
- `register_all(router)` is invoked by `run.py` (Foundation); the Binary agent never edits `router.py`.
