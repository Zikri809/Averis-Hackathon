# Plan 02 — Stage 2: Text Extraction + Alias Table (owner: Text extraction agent)

> Scope: `.txt` route, doc-type sniff (shared), alias table (shared with binary agent),
> value normalizers, missing_value detection. This is the highest-value plan: 192/250 files,
> **33 of 46 defect emails are txt-only** (worth ~0.72 e2e on its own).

## Deliverable

`.txt` SI/BL attachments → 7-field `DocRecord` with evidence; every alias in `pools.LABELS`
resolves correctly; blanks become `null` (→ `missing_value`).

## Files owned

| File | Purpose |
|---|---|
| `app/stage2/router.py` | Extension dispatch; zero-byte check; per-file isolation |
| `app/stage2/txt_parser.py` | Line regex, continuation lines, label/value pairs |
| `app/stage2/aliases.py` | **The** alias table (data), normalization-before-lookup, exact-match longest-first |

## Contracts

**Inbound:** attachment path + bytes (from `loader_client`).

**Outbound:** `DocRecord` per `schema.py`. `evidence[field].label_found` = raw label as written.

**Alias API (other agents import this):**

```python
ALIASES: dict[str, str]                 # normalized alias -> canonical field
def canonical(label: str) -> str | None # None when unmatched
ALIAS_TABLE_HASH: str                   # sha256 of sorted table; enters checkpoint key
```

## Tasks

| # | Task | Verification |
|---|---|---|
| T1 | `aliases.py` from `pools.py:175-188` (the generator's exact source): all 7 field label sets, normalized per v3-A3/A4 | `pytest tests/test_aliases.py` asserts every literal label in `pools.LABELS` for the 7 compare fields resolves |
| T2 | `txt_parser.py`: **indentation guard first** — a line starting with whitespace is a continuation, never a label; then regex `^([^:]{2,40}):\s*(.*)$`; continuation lines absorbed into previous value | unit tests on real files 001, 004, 144 (indented `NEW NO :`), 520 |
| T3 | Router contract: `register(ext, fn)` published here; W2 stub route for `.xlsx/.docx/.pdf` → `NEEDS_REVIEW/unreadable` until the Binary agent registers parsers. **Doc-type sniff is `doctype.py`, owned by the Binary agent** — router calls it, does not implement it | 501–505 → wrong_doc_type; 001 → BL; W2: all binary pairs exit `unreadable` |
| T4 | Value normalizers: parties (first line identity, ON BEHALF OF chain captured), ports (name + code separated), count (`N x size` → int, bare int), weight (comma strip, KG required for txt) | `pytest tests/test_txt_normalize.py` |
| T5 | Blank detection: `???`, `____`, `TBA`, `TBC`, `N/A`, `____MT`, empty → `null` + evidence note | 516–520 → all fields present except blanks; email exits `missing_value` |
| T6 | Multi-line address handling: value = first non-empty line; addresses/`ON BEHALF OF` retained in `raw` evidence | 520 test: identity extracted, chain in evidence |

## Edge cases owned here

| Case | Rule |
|---|---|
| `Gross Weight毛重(KGS)` (51 files, no space before 毛重) | `norm_label` strips non-ASCII → `GROSS WEIGHT` → matches alias (v3-A3) |
| `Notify Party/Intermediate Consignee` contains `Consignee` | **exact** normalized match, longest alias first; never substring match (v3-A4) |
| `To the Order of` (consignee alias) | present in table; resolves to consignee |
| win32 charmap crash (`email_519_SI.txt` has CJK) | every read is `encoding='utf-8', errors='replace'` |
| **Indented continuation containing a colon** (`email_144_SI/_BL`: `  NEW NO : 23, L-BLOCK…`) | Leading-whitespace check runs **before** the label regex; otherwise consignee is corrupted on a gold defect (144) |
| Blank consignee + `ON BEHALF OF` chain (520, 56 files total) | null consignee → `missing_value` (never guess from chain) |
| Continuation lines | indented lines append to previous value; label regex must not match them |
| Two lines matching same field | prefer non-blank, record both, confidence 0.5 (display-only) |
| Port `(MYPKG)` code | split name vs code; both kept in evidence; comparison uses name only |
| Weight without KG on a `.txt` line | `null` + note (correct `missing_value`) — but **only for text formats** |
| `email_519_SI` blank shipper | → `missing_value` |
| Binary attachments during W2 | Router stub returns `NEEDS_REVIEW/unreadable` until Binary agent registers; replaced in W3 |

## Tests

- `test_aliases.py` — iterate `pools.LABELS` for the 7 compare fields; every literal resolves; assert
  `canonical("NOTIFY PARTY/INTERMEDIATE CONSIGNEE") == "notify_party"` and
  `canonical("CONSIGNEE") == "consignee"` (order independence via exact match).
- `test_txt_parser.py` — real-file snapshots: 001 (both sides), 004 (misleading subject), 144 (indented colon line), 519 (CJK + blanks), 520 (blanks/chain).
- `test_txt_normalize.py` — weight/count/port/party tables from `../ARCHITECTURE.md` §1.
- `test_doctype.py` — **owned by the Binary agent** (plan 03); this plan only calls it.

## Definition of done (W2-part-A gate)

1. `tools/verify_extraction.py --scope txt` → all txt pairs parsed; agreement structure matches GT
   (see `06-verification.md` §2) with **zero** parser bugs on OK pairs.
2. All 16 LOCODE-identical port defects have differing name values extracted on both sides.
3. 516–520 exit `missing_value`; 519/520 fields correctly null; 144 consignee extracted cleanly.
4. `pytest tests/test_aliases.py tests/test_txt_*.py -q` green.
5. `ALIAS_TABLE_HASH` stable and exported; `router.register()` published and documented.

## Dependencies

- Imports: `schema`, `normalize`, `state` (Foundation), `doctype` (Binary agent — B1 lands first).
- Provides: `aliases.py` + `router.register()` to the Binary agent; `ALIAS_TABLE_HASH` to Foundation.
- W2 binary stub route is a temporary contract; the Binary agent's `register_all(router)` is called by
  `run.py` (Foundation) at W3, replacing the stub without editing `router.py`.
