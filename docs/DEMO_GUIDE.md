# Demo Guide — CNC Part Intelligence Level 1

Use this script for a live demonstration. The bundled sample workbook is **synthetic** and labeled as such in the UI/README. If you have a real manufacturing workbook, substitute it in steps 2–3 and use a part number that exists in that file.

---

## Prerequisites (before the demo)

```bash
cd /path/to/CNC
source .venv/bin/activate
cp .env.example .env   # if not already configured
# Edit .env: set OPENROUTER_API_KEY and OPENROUTER_MODEL
streamlit run app.py
```

Confirm the browser opens to the Streamlit URL (default `http://localhost:8501`).

---

## Demonstration plan

### 1. Start the application

- Show the header: **CNC Part Intelligence**
- Point out the badge: `Level 1 — Excel + LLM`
- Note the subtitle about evidence-based analysis

### 2. Load the manufacturing workbook

**Option A — sample dataset**

- Sidebar → **Default dataset**
- File: `sample_manufacturing_records.xlsx`
- Sheet: `Manufacturing Records`
- Part-number column: `Part Number`

**Option B — real dataset**

- Sidebar → **Upload file**
- Select the organization’s workbook
- Choose the correct sheet and part-number column when prompted

Call out dataset status: record count, unique parts, selected column.

### 3. Search for an existing part number

- Enter `2280` (sample) or a known real part number
- Click **Search**
- Confirm a success message that the record was found

### 4. Show the retrieved Excel record

- In **Part Overview**, walk through the field/value table
- Emphasize that only columns present in the workbook are shown
- Empty cells appear as `(not recorded)` — not as invented facts

### 5. Ask a question whose answer is present

Example (sample data):

> What material is used?

- Submit the question
- For a single-field match, the app may answer **without** calling the LLM
- Or ask a summary question to exercise OpenRouter when configured

### 6. Show the evidence

In **AI Answer**, highlight:

- Status (`answered`)
- Natural-language answer
- Evidence block:
  - Source filename
  - Sheet name
  - Part number
  - Field / recorded value (e.g. Material)

Stress that evidence metadata is generated in Python from the retrieved row.

### 7. Ask a question whose answer is absent

Example:

> What is the cycle time for this part?

### 8. Demonstrate acknowledgment of missing information

- Confirm the answer states the Excel record does **not** contain that information
- Status should reflect `not_found` / missing information rather than a guessed value
- No fabricated units, machines, or process details

### 9. Search for a nonexistent part

- Search for a part number that does not exist (e.g. `99999`)
- Show the clear no-match message
- Confirm that **no LLM call** is made for a failed lookup

**Optional:** Search `9901` in the sample data to demo **duplicate** handling — the UI lists matching rows and asks you to select one.

**Optional:** Search `00123` vs `123` to show leading-zero identifiers are distinct.

### 10. Explain the Level 1 boundary and future enhancements

- Ask a PDF/IGES-oriented question, e.g. *What tolerances are on the PDF drawing?*
- Show the Level 1 decline message
- Summarize roadmap:
  - **Level 2:** PDF engineering drawing analysis
  - **Level 3:** IGES geometry extraction and cross-source validation

---

## Demo tips

- Keep `.env` ready so AI answers work when you want them; part lookup still works offline.
- If OpenRouter is unavailable mid-demo, show the Excel overview and the graceful error — still a valid Level 1 demo of retrieval + honesty.
- Do not claim PDF/IGES were analyzed.
- Do not present the synthetic sample as real production data.
