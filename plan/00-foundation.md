# Plan 00 — Foundation (owner: Foundation agent)

> Scope: skeleton, schema, dataset client, normalization helpers, checkpointing, orchestrator.
> **Everything the other agents import lives here.** No stage logic in this plan.

## Deliverable

A runnable pipeline skeleton that reads all 520 emails, produces a valid 520-key submission from
the *default* records (GENERAL/OK), and proves the submission path end-to-end. This is the W0 gate.

## Files owned

| File | Purpose |
|---|---|
| `app/schema.py` | All record dataclasses/TypedDicts + `SCHEMA_VERSION` |
| `app/normalize.py` | String normalization, alias-normalization, KG parsing, blank tokens |
| `app/loader_client.py` | Wraps organizers' `loader.Inbox` (local dir or HTTP) |
| `app/checkpoint.py` | Append-only JSONL checkpoint, idempotent resume |
| `app/state.py` | `SCORED_RUN` flag, paths (`DATA_DIR`, `STATE_DIR`, `OUTBOX_DIR`), `assert_520` |
| `app/run.py` | Orchestrator: load → stage1 → stage2 → stage3 → assemble → write |
| `app/__init__.py`, `app/stage2/__init__.py`, `app/extensions/__init__.py` | package inits |

## Contracts (schema.py — authoritative)

```python
SCHEMA_VERSION = "3.0"

# 7 compare fields, exact scorer vocabulary
COMPARE_FIELDS = ["shipper", "consignee", "notify_party", "port_of_loading",
                  "port_of_discharge", "container_count", "gross_weight_kg"]

@dataclass
class DocRecord:
    fields: dict[str, str | int | float | None]   # exactly COMPARE_FIELDS keys
    readable: bool
    source_format: str        # "txt" | "xlsx" | "docx" | "pdf" | "ocr"
    evidence: dict[str, FieldEvidence]

@dataclass
class FieldEvidence:
    value: str | int | float | None
    raw: str | None           # the raw line/cell text
    label_found: str | None   # raw label as found
    source_format: str
    confidence: float         # 1.0 alias | 0.5 conflict | llm score (display-only; no OCR value — E5)

@dataclass
class ExtractionResult:
    si_doc: DocRecord | None
    bl_doc: DocRecord | None
    doc_status: str           # READY | NEEDS_REVIEW
    review_reason: str | None # wrong_doc_type|missing_attachment|unreadable|missing_value

@dataclass
class Verdict:
    has_defect: bool
    defect_fields: list[str]
    diff_report: dict[str, dict]   # {field: {"si": v, "bl": v}}
```

**Submission record (exact keys, verified against `sample_submission.json`):**

```python
{"category": str, "status": "OK"|"MISMATCH"|"NEEDS_REVIEW",
 "review_reason": str|None, "defect_fields": list[str], "has_defect": bool}
```

`decided_by` may be added (optional; feeds `rule_pct`) but must never replace a required key.

## Tasks

| # | Task | Verification |
|---|---|---|
| F1 | `schema.py` with the dataclasses + `SCHEMA_VERSION`; unit test asserts key sets | `pytest tests/test_schema.py` |
| F2 | `normalize.py`: `norm_label()` (ASCII-strip → uppercase → strip parens incl. CJK → strip punct → collapse ws), `norm_compare()` (uppercase → strip punct → collapse ws), `parse_weight()`, `parse_count()`, `is_blank()` | `pytest tests/test_normalize.py` |
| F3 | `loader_client.py`: `emails()`, `read_bytes(path)`, `read_text(path)`; local + HTTP modes | smoke: 520 emails, 250 attachment reads |
| F4 | `checkpoint.py`: append-only JSONL keyed `sha256(email_id + attachment-bytes-hash + ALIAS_TABLE_HASH + LEARNED_ALIAS_HASH + SCHEMA_VERSION)`; `LEARNED_ALIAS_HASH` defaults to `sha256(b"")` when absent (scored run); `load()`, `put()`, `flush()` | `pytest tests/test_checkpoint.py` incl. resume-after-kill, alias-hash invalidation, learned-hash invalidation |
| F5 | `state.py`: `SCORED_RUN` flag, path resolution, `assert_520(sub)` helper, `llm_cache_path()` | `pytest tests/test_state.py` |
| F6 | `run.py`: end-to-end with stub stages returning defaults; **gate ordering: category first, then attachment rule**; writes `submission.json` with exactly 520 keys | `python -m app.run --data data_v2 --out submission.json` then `tools/preflight.py submission.json` |
| F7 | Extension wiring: import extension hooks **only when `SCORED_RUN != "1"`**; under `SCORED_RUN=1` the extension modules are never imported | `pytest tests/test_scored_run.py::test_extensions_not_imported` |

## Edge cases owned here

| Case | Rule |
|---|---|
| Zero attachments | **Category gate first:** only after `category == BL_COMPARISON`, then 0 att + body matches `/dropped\|still missing/i` → `missing_attachment`; otherwise continue as normal (94 emails, 91 OK). The phrase also occurs in 23 INVOICE_QUERY bodies — the category gate prevents false escalations |
| SI-only (507, 509) | exactly 1 attachment → `missing_attachment` |
| 2 attachments but one unreadable | other doc still parsed; whole email exits `unreadable` |
| Corrupt/missing file path | per-file try/except → `readable:false`; never raises out of `run.py` |
| Crash mid-run | checkpoint resume: rerun produces identical submission |
| Missing email in output | `assert_520()` raises before write; preflight catches it again |
| `decided_by` absent | submission still valid; `rule_pct` is `None` |
| Extensions under `SCORED_RUN=1` | never imported (F7) |

## Tests

> **Ownership:** the five contract test files below are **owned by the Verification agent** (plan 06,
> `tools/` + contract tests). The Foundation agent implements the contracts and fixes any failures,
> but does not edit these test files.

- `test_schema.py` — exact submission key set; `COMPARE_FIELDS` order/length.
- `test_normalize.py` — table-driven: `Gross Weight毛重(KGS)` → `GROSS WEIGHT` (v3-A3);
  `Notify Party/Intermediate Consignee` must not normalize into `CONSIGNEE` (v3-A4);
  `128.54 KG`→128.54; `126,544 KGS`→126544.0; `N/A`, `TBA`, `???`, `____MT` → blank;
  `341715` (int, no unit) accepted as KG for binary formats (v3-A2).
- `test_checkpoint.py` — resume after simulated crash; alias-table hash change invalidates;
  learned-alias hash change invalidates.
- `test_run_stub.py` — 520 keys, all categories valid, all statuses valid, invariants hold
  (`has_defect == (status == "MISMATCH")`); **23 INVOICE_QUERY negatives** do not escalate
  despite matching the dropped/still-missing phrase.

## Definition of done (W0 gate)

1. `python -m app.run --data data_v2 --out submission.json` exits 0, writes 520 keys.
2. `tools/preflight.py submission.json` green (see `06-verification.md`).
3. `POST /submit` with that file returns HTTP 200 and `n_emails == 520` (baseline ≈ 0.0124).
4. `pytest tests/ -q` green.
5. No stage module imported by `run.py` yet (stubs only) — W0 is a plumbing gate, not a scoring gate.
6. `SCHEMA_VERSION`, `ALIAS_TABLE_HASH`, `LEARNED_ALIAS_HASH` are exported and documented.

## Dependencies / hand-offs

- Blocks: everyone. W1+ agents code against these contracts only.
- Publishes: schema version, `normalize` API, checkpoint key format, `assert_520`, `state` paths.
- F7 coordinates with the Extensions agent (X6 verifies only) and the Ops agent (`server.py`).
