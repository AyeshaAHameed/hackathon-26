# CNC Part Intelligence — Level 1

Evidence-based manufacturing record analysis for CNC components.  
**Level 1 (Core):** Excel / CSV lookup + grounded LLM answers via OpenRouter.

PDF engineering drawings and IGES 3D models are **not** analyzed in this version. Those capabilities are reserved for Level 2 and Level 3.

---

## Overview

Given a CNC part number, the application:

1. Loads a manufacturing workbook (`.xlsx`, `.xls`, or `.csv`).
2. Performs an **exact** part-number lookup (no embeddings / vector search).
3. Displays the full retrieved record.
4. Answers natural-language questions using **only** that record, via a configurable OpenRouter model.
5. Shows programmatically generated evidence (workbook, sheet, part number, columns).
6. Acknowledges missing information instead of inventing manufacturing facts.

Example part number in the bundled sample dataset: `2280`.

> The repository ships a **synthetic** sample workbook under `data/` for demos and tests. Replace it with your real manufacturing records or upload a file in the UI.

---

## Features

- Streamlit engineering dashboard (light industrial theme)
- Workbook upload or default local dataset
- Multi-sheet selection and part-number column confirmation
- Exact part-number matching with leading-zero preservation
- Safe handling of Excel numeric cells (e.g. `2280.0` → `2280`)
- Duplicate part-number resolution (user selects the intended row)
- Question routing with direct field answers when possible
- Grounded OpenRouter LLM calls (single verified record only)
- Evidence validation against the retrieved row
- Offline-friendly: part lookup works without an API key
- Automated pytest suite with mocked HTTP (no paid API calls)

---

## Architecture

```
cnc-part-intelligence/
├── app.py                          # Streamlit UI + orchestration
├── requirements.txt
├── .env.example
├── pyproject.toml
├── README.md
├── TECHNICAL_DOCUMENTATION.md
├── src/cnc_intelligence/
│   ├── config.py                   # Settings / OpenRouter config
│   ├── data_loader.py              # Excel/CSV ingestion
│   ├── schema_detector.py          # Part-number column suggestions
│   ├── part_lookup.py              # Exact identifier matching
│   ├── question_router.py          # Question classification
│   ├── llm_service.py              # OpenRouter client + prompts
│   ├── answer_validator.py         # Schema + evidence checks
│   └── models.py                   # Pydantic models
├── tests/
├── data/                           # Sample / local workbooks
└── docs/DEMO_GUIDE.md
```

Retrieval always precedes generation. The LLM never selects the part record.

---

## Prerequisites

- Python **3.11+** (3.12 / 3.13 / 3.14 also supported)
- macOS or Linux
- An [OpenRouter](https://openrouter.ai/) API key (optional for lookup-only demos)
- A manufacturing workbook, or use the bundled sample

---

## Installation (macOS / Linux)

```bash
cd /path/to/CNC

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

---

## Configuration

Copy the example environment file and edit it:

```bash
cp .env.example .env
```

Example `.env`:

```env
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=your_openrouter_model_id
OPENROUTER_SITE_URL=http://localhost:8501
OPENROUTER_APP_NAME=CNC Part Intelligence
REQUEST_TIMEOUT_SECONDS=45
MAX_OUTPUT_TOKENS=1200
LLM_TEMPERATURE=0.1
MAX_UPLOAD_SIZE_MB=25
```

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | For AI answers | OpenRouter secret (never commit) |
| `OPENROUTER_MODEL` | For AI answers | Any OpenRouter model ID you choose |
| `OPENROUTER_SITE_URL` | No | Optional referer header |
| `OPENROUTER_APP_NAME` | No | Optional app title header |
| `REQUEST_TIMEOUT_SECONDS` | No | HTTP timeout (default 45) |
| `MAX_OUTPUT_TOKENS` | No | Model output limit (default 1200) |

The model is **fully configurable**. Do not hardcode a provider model in source.  
API base URL: `https://openrouter.ai/api/v1`

---

## Dataset

### Bundled sample (synthetic)

- `data/sample_manufacturing_records.xlsx`
  - Sheet `Manufacturing Records` — main demo rows (includes part `2280`)
  - Sheet `Alternate Schema` — different column names for sheet-selection demos
- `data/sample_manufacturing_records.csv` — CSV variant

### Using your own data

1. Place an `.xlsx` / `.xls` / `.csv` file in `data/`, **or**
2. Upload it from the Streamlit sidebar.

### Schema requirements

- At least one header row and one data row
- A column that identifies parts (e.g. `Part Number`, `Part No`, `PN`)
- The app suggests likely part-number columns; when ambiguous, **you must select** the correct column
- No assumed fixed schema — answers depend on columns actually present

---

## Running the application

```bash
source .venv/bin/activate
streamlit run app.py
```

Open the URL shown in the terminal (typically `http://localhost:8501`).

### Quick demo flow

1. Confirm the default sample dataset is loaded (or upload your workbook).
2. Select sheet `Manufacturing Records` and part-number column `Part Number`.
3. Search for `2280`.
4. Review the Part Overview table.
5. Ask: *What material is used?*
6. Inspect the Evidence section (source file, sheet, column, value).
7. Ask something absent (e.g. cycle time) and confirm a clear “not recorded” response.

See [`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md) for a full demonstration script.

---

## Running tests

```bash
source .venv/bin/activate
pytest -q
```

All OpenRouter calls are mocked. Tests do **not** require an API key and do not make paid network requests.

Lint / format with Ruff:

```bash
ruff check src tests app.py
ruff format src tests app.py
```

---

## Example questions

These are illustrative. Actual answers depend on columns in your workbook.

- What is this part?
- What material is used?
- What manufacturing process is recorded?
- Which machine is associated with this part?
- What information is available about this component?
- Summarize the manufacturing record.
- Is the required information available in the Excel record?

Questions that require PDF drawings or IGES geometry are declined with a Level 1 scope message.

---

## Common errors and troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| “OpenRouter API key is not configured” | Missing / placeholder `.env` | Set `OPENROUTER_API_KEY` |
| “model was not found” | Invalid `OPENROUTER_MODEL` | Use a valid OpenRouter model ID |
| “No manufacturing record found” | Wrong sheet, column, or part ID | Confirm sheet + part-number column; check spelling |
| “Could not determine the part-number column” | Unusual headers | Select the column manually in the sidebar |
| “File exceeds the maximum upload size” | Large workbook | Increase `MAX_UPLOAD_SIZE_MB` or trim the file |
| “Unsupported file format” | Wrong extension | Use `.xlsx`, `.xls`, or `.csv` |
| AI fails but record still shows | Network / rate limit / timeout | Review the error banner; Excel data remains usable |
| Leading zeros missing | Excel stored IDs as numbers | Export the column as text in the source workbook; Level 1 cannot recover lost zeros |

---

## Current limitations (Level 1)

- Excel / CSV only — no PDF or IGES analysis
- Exact part-number match only (no fuzzy / semantic part search)
- One selected record per Q&A turn
- LLM explanations are grounded and validated for cited columns, but free-text wording is not a formal proof of every sentence
- Synthetic sample data is for demonstration, not production manufacturing truth

---

## Roadmap

| Level | Capability | Status |
|-------|------------|--------|
| **1** | Excel record lookup + grounded LLM Q&A | **Implemented** |
| **2** | PDF engineering drawing ingestion / extraction | Future |
| **3** | IGES geometry extraction + cross-source validation | Future |
| Stretch | Robust support for any part number in large datasets | Partial (exact index today) |

Architecture keeps evidence sources abstract so PDF/IGES providers can be added later without rewriting Level 1.

---

## Security notes

- Keep `.env` out of Git (already listed in `.gitignore`)
- Never commit API keys
- Uploads are size-limited and type-checked
- Workbook cell values are treated as untrusted data in prompts
- API keys are never rendered in the UI

---

## License / problem context

Built for the SPEC'26 AI Problem: LLM-Based CNC Part Analysis — Level 1 (Core).
