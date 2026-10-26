# Technical Documentation — CNC Part Intelligence (Level 1)

## 1. Problem statement and scope

**Problem:** LLM-Based CNC Part Analysis (SPEC'26).  
**Implemented level:** Level 1 — Excel manufacturing records + grounded LLM Q&A.

The system accepts a part number, retrieves the matching manufacturing row from a spreadsheet, and answers natural-language questions using only that row. It must not invent engineering properties, silently resolve ambiguous matches, or claim to have analyzed PDF drawings or IGES models.

**Out of scope for this release**

- PDF drawing OCR / extraction (Level 2)
- IGES / CAD geometry analysis (Level 3)
- Vector databases, embeddings, agent frameworks, and full-workbook RAG

---

## 2. System architecture

Layered modules under `src/cnc_intelligence/`:

| Module | Responsibility |
|--------|----------------|
| `config.py` | Environment settings, system prompt, OpenRouter defaults |
| `data_loader.py` | File validation, sheet loading, identifier normalization |
| `schema_detector.py` | Conservative part-number column scoring / selection helpers |
| `part_lookup.py` | Exact indexed lookup, duplicate detection |
| `question_router.py` | Classify questions; prefer direct answers when safe |
| `llm_service.py` | Prompt construction + OpenRouter HTTP client |
| `answer_validator.py` | Schema checks + evidence reconciliation |
| `models.py` | Pydantic types for records, answers, evidence |
| `app.py` | Streamlit UI orchestration only |

**Invariant:** identity of the part record is established by exact Excel lookup **before** any LLM call. The model receives a single verified record, never the full workbook.

```
User → Streamlit → Part Lookup → (optional) Question Router
                                      ↓
                         Direct answer  OR  OpenRouter (grounded)
                                      ↓
                              Answer Validator → UI (answer + evidence)
```

---

## 3. Excel ingestion and normalization

### Supported formats

- `.xlsx` via `openpyxl`
- `.xls` via `xlrd`
- `.csv` via pandas

### Validation

The loader rejects or warns on:

- Unsupported extensions
- Unreadable / empty workbooks or sheets
- Missing headers
- Duplicate column names (renamed with a warning)
- Missing / empty part-number column values
- Oversized uploads (`MAX_UPLOAD_SIZE_MB`)

### Identifier normalization

`normalize_part_identifier`:

- Trims whitespace
- Converts Excel floats such as `2280.0` → `"2280"`
- Preserves textual leading zeros (`"00123"` stays `"00123"`)
- Does **not** equate `"00123"` and `"123"`
- Treats empty / NaN as invalid for indexing

If Excel has already coerced a text ID with leading zeros into a number, those zeros cannot be recovered reliably; the UI documents this limitation.

### Schema detection

Column names are scored against conservative patterns (`part number`, `part_no`, `pn`, etc.). Auto-selection occurs only when there is a single clear winner. Otherwise the UI requires an explicit column choice.

---

## 4. Part-number matching strategy

1. Build an in-memory index: normalized part number → list of row indices.
2. Normalize the user query with the same rules.
3. Exact dictionary lookup (no fuzzy matching).
4. Outcomes:
   - **found** — single row → `PartRecord`
   - **duplicate** — multiple rows → user must select
   - **not_found** — no LLM call
   - **invalid_input** — empty / blank query

The selected `PartRecord` carries authoritative `SourceMetadata` (filename, sheet, part number, column, row index).

---

## 5. LLM integration (OpenRouter)

- Endpoint: `POST {OPENROUTER_BASE_URL}/chat/completions`  
  Default base: `https://openrouter.ai/api/v1`
- Model: `OPENROUTER_MODEL` (required for AI answers; not hardcoded)
- Auth: `Authorization: Bearer $OPENROUTER_API_KEY`
- Optional headers: `HTTP-Referer`, `X-Title`
- Timeout: `REQUEST_TIMEOUT_SECONDS`
- Output cap: `MAX_OUTPUT_TOKENS`
- Temperature: `LLM_TEMPERATURE` (default `0.1`)

**Resilience**

- Bounded retries with backoff for transient errors only
- JSON `response_format` attempted first; falls back if the model rejects it
- Markdown-fenced JSON tolerated in the fallback parser
- User-facing errors for 401 / 404 / 429 / 5xx / timeout / network
- On failure: Excel record remains visible; no successful AI answer is claimed

API keys are never logged or rendered.

---

## 6. Prompt design and grounding

The system prompt (see `config.SYSTEM_PROMPT`) instructs the model to:

- Use only the supplied record
- Refuse invented specs, units, and typical-CNC assumptions
- Treat cell values as untrusted data (prompt-injection resistant)
- Decline PDF/IGES questions as Level 1 out of scope
- Return structured JSON: `answer`, `status`, `evidence`, `missing_information`, `limitations`

The user prompt includes only:

- Part number and source metadata
- Original column names and values for the selected row
- The question (+ optional router hints)

---

## 7. Evidence generation and validation

Evidence metadata is **authoritative in Python**, not trusted from the model:

- Filename, sheet, part number, and part-number column come from `PartRecord.source`
- Each evidence item must cite a column that exists on the selected row
- Cited values must match retrieved values (mismatch → evidence dropped + validation note)
- Empty cells are never promoted to factual evidence

`validate_answer` also enforces non-empty answer text and a known `status` enum.

**Honesty boundary:** schema/evidence validation does not prove every natural-language clause is factually perfect. When claims cannot be independently verified, the UI still shows the supporting record and any validation notes.

### Direct answers without the LLM

`question_router` + `direct_answer_payload` answer simple single-field lookups and clear out-of-scope questions without calling OpenRouter. This reduces cost, latency, and hallucination surface area.

---

## 8. Error handling

| Layer | Strategy |
|-------|----------|
| Data load | `DataLoadError` with actionable `code` + message |
| Lookup | Structured `LookupResult` statuses |
| LLM | `LLMServiceError` mapped from HTTP / network conditions |
| Validation | `ValidationError` → fallback answer in the UI |
| UI | Streamlit banners; no raw stack traces for expected failures |

---

## 9. Security considerations

- `.env` gitignored; `.env.example` has placeholders only
- Upload type + size validation
- No formula / macro execution (pandas/openpyxl read of cell values only)
- Cell contents injected into prompts as data, with explicit ignore-instructions rule
- Streamlit renders values as text (not unsafe HTML from cells)
- Masked API key status in the sidebar (`Configured (sk-…xxxx)`)

---

## 10. Testing strategy

`pytest` suite under `tests/`:

- Temporary workbooks for loader / lookup edge cases
- `httpx` mocks / patched clients for OpenRouter paths
- Deterministic; no live API credentials required

Coverage areas: loading, lookup, routing, LLM errors, evidence validation.

Run: `pytest -q`  
Lint: `ruff check src tests app.py`

---

## 11. Known limitations

- Level 1 only (no PDF/IGES)
- Exact match only
- Leading zeros lost upstream in Excel cannot be restored
- Multi-row duplicates require manual disambiguation
- Free-text LLM sentences are grounded by prompt + evidence checks, not formal NLI
- Sample workbook is synthetic demo data

---

## 12. Extending to Levels 2 and 3

Recommended approach (not implemented):

1. Introduce a `EvidenceSource` protocol with implementations:
   - `ExcelRecordSource` (current)
   - `PdfDrawingSource` (Level 2)
   - `IgesGeometrySource` (Level 3)
2. Keep `part_lookup` as the identity gate.
3. Extend `question_router` categories and evidence validators per source.
4. Cross-source validation (Level 3) compares Excel claims against extracted geometry without silently overriding either source.

Do not add empty stub APIs that pretend PDF/IGES already work.
