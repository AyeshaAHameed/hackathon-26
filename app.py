"""CNC Part Intelligence — Streamlit Level 1 application."""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure src/ is on the path when running via `streamlit run app.py`
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cnc_intelligence.answer_validator import (  # noqa: E402
    ValidationError,
    build_fallback_answer,
    validate_answer,
)
from cnc_intelligence.config import get_settings  # noqa: E402
from cnc_intelligence.data_loader import (  # noqa: E402
    DataLoadError,
    LoadedDataset,
    list_sheet_names,
    load_dataset,
    validate_extension,
)
from cnc_intelligence.llm_service import (  # noqa: E402
    LLMServiceError,
    OpenRouterClient,
    direct_answer_payload,
)
from cnc_intelligence.models import AnswerStatus, EvidenceItem, PartRecord, ValidatedAnswer  # noqa: E402
from cnc_intelligence.part_lookup import (  # noqa: E402
    build_part_index,
    example_part_numbers,
    lookup_part,
)
from cnc_intelligence.question_router import route_question, suggested_questions  # noqa: E402
from cnc_intelligence.schema_detector import (  # noqa: E402
    auto_select_part_number_column,
    suggest_part_number_columns,
)

st.set_page_config(
    page_title="CNC Part Intelligence",
    page_icon="C",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

    :root {
        --bg: #f4f6f8;
        --panel: #ffffff;
        --text: #1f2933;
        --muted: #52606d;
        --accent: #3d6b8e;
        --accent-soft: #e8f0f6;
        --border: #d9e2ec;
        --danger: #9b2c2c;
        --ok: #276749;
        --warn: #975a16;
    }

    .stApp {
        background: var(--bg);
        color: var(--text);
        font-family: 'IBM Plex Sans', sans-serif;
    }

    h1, h2, h3, h4 {
        color: var(--text) !important;
        font-family: 'IBM Plex Sans', sans-serif !important;
        letter-spacing: -0.01em;
    }

    .cpi-header {
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
    }
    .cpi-header h1 {
        margin: 0 0 0.25rem 0;
        font-size: 1.75rem;
        font-weight: 700;
    }
    .cpi-header .subtitle {
        color: var(--muted);
        margin: 0;
        font-size: 1rem;
    }
    .cpi-badge {
        display: inline-block;
        margin-top: 0.75rem;
        background: var(--accent-soft);
        color: var(--accent);
        border: 1px solid #c5d8e8;
        border-radius: 4px;
        padding: 0.2rem 0.55rem;
        font-size: 0.8rem;
        font-weight: 600;
        font-family: 'IBM Plex Mono', monospace;
    }
    .cpi-panel {
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
    }
    .cpi-meta {
        color: var(--muted);
        font-size: 0.9rem;
    }
    .cpi-status-answered { color: var(--ok); font-weight: 600; }
    .cpi-status-partial { color: var(--warn); font-weight: 600; }
    .cpi-status-missing { color: var(--danger); font-weight: 600; }
    .cpi-evidence-item {
        border-left: 3px solid var(--accent);
        padding: 0.5rem 0.75rem;
        margin: 0.4rem 0;
        background: var(--accent-soft);
        border-radius: 0 4px 4px 0;
        font-size: 0.92rem;
    }
    .cpi-mono {
        font-family: 'IBM Plex Mono', monospace;
    }
    div[data-testid="stSidebar"] {
        background: #eef2f6;
        border-right: 1px solid var(--border);
    }
    .stButton > button {
        border-radius: 6px;
        border: 1px solid var(--accent);
        background: var(--accent);
        color: white;
        font-weight: 600;
    }
    .stButton > button:hover {
        background: #2f5573;
        border-color: #2f5573;
        color: white;
    }
</style>
"""


def init_session_state() -> None:
    defaults = {
        "dataset": None,
        "part_index": None,
        "lookup_result": None,
        "selected_record": None,
        "selected_match_index": 0,
        "last_answer": None,
        "last_question": None,
        "dataset_fingerprint": None,
        "uploaded_bytes": None,
        "uploaded_name": None,
        "selected_sheet": None,
        "selected_pn_column": None,
        "search_input": "",
        "question_area": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def fingerprint_source(name: str, sheet: str, pn_col: str, payload: bytes | None) -> str:
    h = hashlib.sha256()
    h.update(name.encode())
    h.update(sheet.encode())
    h.update(pn_col.encode())
    if payload is not None:
        h.update(payload[:4096])
        h.update(str(len(payload)).encode())
    return h.hexdigest()


def reset_part_selection() -> None:
    st.session_state.lookup_result = None
    st.session_state.selected_record = None
    st.session_state.selected_match_index = 0
    st.session_state.last_answer = None
    st.session_state.last_question = None


def reset_all() -> None:
    reset_part_selection()
    st.session_state.dataset = None
    st.session_state.part_index = None
    st.session_state.dataset_fingerprint = None
    st.session_state.uploaded_bytes = None
    st.session_state.uploaded_name = None
    st.session_state.selected_sheet = None
    st.session_state.selected_pn_column = None
    st.session_state.search_input = ""
    st.session_state.question_area = ""


@st.cache_data(show_spinner=False)
def cached_list_sheets(filename: str, file_bytes: bytes) -> list[str]:
    return list_sheet_names(file_bytes, filename)


@st.cache_data(show_spinner=False)
def cached_load_bytes(
    filename: str,
    file_bytes: bytes,
    sheet_name: str,
    part_number_column: str | None,
) -> LoadedDataset:
    return load_dataset(
        file_bytes,
        filename=filename,
        sheet_name=sheet_name,
        part_number_column=part_number_column,
    )


def render_header() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="cpi-header">
            <h1>CNC Part Intelligence</h1>
            <p class="subtitle">Evidence-based manufacturing record analysis powered by AI</p>
            <span class="cpi-badge">Level 1 — Excel + LLM</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(settings) -> None:
    with st.sidebar:
        st.markdown("### Dataset")
        uploaded = st.file_uploader(
            "Manufacturing workbook",
            type=["xlsx", "xls", "csv"],
            help=f"Upload an Excel or CSV file (max {settings.max_upload_size_mb} MB).",
        )
        if uploaded is not None:
            raw = uploaded.getvalue()
            if len(raw) > settings.max_upload_bytes:
                st.error(
                    f"File exceeds the maximum upload size of "
                    f"{settings.max_upload_size_mb} MB."
                )
                st.session_state.dataset = None
                return
            st.session_state.uploaded_bytes = raw
            st.session_state.uploaded_name = uploaded.name

        if not st.session_state.uploaded_bytes or not st.session_state.uploaded_name:
            st.info("Upload a manufacturing workbook to continue.")
            st.caption(
                "PDF drawing and IGES 3D model analysis are not implemented in Level 1."
            )
            if st.button("Clear / Reset", use_container_width=True):
                reset_all()
                st.rerun()
            return

        filename = st.session_state.uploaded_name
        file_bytes = st.session_state.uploaded_bytes

        try:
            sheet_names = cached_list_sheets(filename, file_bytes)
        except DataLoadError as exc:
            st.error(exc.message)
            return

        if not sheet_names:
            st.info("Upload a manufacturing workbook to continue.")
            return

        selected_sheet = st.selectbox(
            "Sheet",
            sheet_names,
            index=(
                sheet_names.index(st.session_state.selected_sheet)
                if st.session_state.selected_sheet in sheet_names
                else 0
            ),
        )
        st.session_state.selected_sheet = selected_sheet

        pn_column = _resolve_part_number_column(
            filename=filename,
            file_bytes=file_bytes,
            sheet_name=selected_sheet,
        )
        if pn_column is None:
            return

        st.session_state.selected_pn_column = pn_column

        try:
            dataset = cached_load_bytes(filename, file_bytes, selected_sheet, pn_column)
        except DataLoadError as exc:
            st.error(exc.message)
            st.session_state.dataset = None
            return

        fp = fingerprint_source(filename, selected_sheet, pn_column, file_bytes)
        if st.session_state.dataset_fingerprint != fp:
            reset_part_selection()
            st.session_state.dataset_fingerprint = fp

        st.session_state.dataset = dataset
        st.session_state.part_index = build_part_index(dataset)

        st.markdown("### Dataset status")
        st.success("Dataset loaded")
        st.markdown(
            f"<div class='cpi-meta'>"
            f"<div>File: <span class='cpi-mono'>{dataset.filename}</span></div>"
            f"<div>Sheet: <span class='cpi-mono'>{dataset.sheet_name}</span></div>"
            f"<div>Records: {dataset.record_count}</div>"
            f"<div>Unique parts: {dataset.unique_part_count}</div>"
            f"<div>Part column: <span class='cpi-mono'>{dataset.part_number_column}</span></div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        for warning in dataset.warnings:
            st.warning(warning)

        st.markdown("---")
        st.caption(
            "PDF drawing and IGES 3D model analysis are not implemented in Level 1."
        )

        if st.button("Clear / Reset", use_container_width=True):
            reset_all()
            st.rerun()


def _peek_columns(filename: str, file_bytes: bytes, sheet_name: str) -> list[str]:
    ext = validate_extension(filename)
    buffer = io.BytesIO(file_bytes)
    if ext == ".csv":
        df = pd.read_csv(buffer, nrows=0)
        return [str(c) for c in df.columns]
    engine = "openpyxl" if ext == ".xlsx" else "xlrd"
    df = pd.read_excel(buffer, sheet_name=sheet_name, nrows=0, engine=engine)
    return [str(c) for c in df.columns]


def _resolve_part_number_column(
    filename: str,
    file_bytes: bytes,
    sheet_name: str,
) -> str | None:
    try:
        columns = _peek_columns(filename, file_bytes, sheet_name)
    except Exception as exc:
        st.error(f"Unable to inspect columns: {exc}")
        return None

    candidates = suggest_part_number_columns(columns)
    auto = auto_select_part_number_column(columns)

    if auto and (
        st.session_state.selected_pn_column is None
        or st.session_state.selected_pn_column not in columns
    ):
        default_col = auto
    elif st.session_state.selected_pn_column in columns:
        default_col = st.session_state.selected_pn_column
    elif candidates:
        default_col = candidates[0]
    elif columns:
        default_col = columns[0]
    else:
        st.error("No columns found in the selected sheet.")
        return None

    options = columns
    help_text = "Select the column that contains part identifiers."
    if len(candidates) > 1 and auto is None:
        st.info(
            "Multiple possible part-number columns detected. "
            "Please confirm the correct column."
        )
        help_text = f"Suggested: {', '.join(candidates)}"

    index = options.index(default_col) if default_col in options else 0
    return st.selectbox("Part-number column", options, index=index, help=help_text)


def render_part_search(dataset: LoadedDataset) -> None:
    st.markdown("#### A. Part Search")
    examples = example_part_numbers(dataset, limit=5)
    example_hint = f"Examples from dataset: {', '.join(examples)}" if examples else ""

    cols = st.columns([3, 1])
    with cols[0]:
        part_input = st.text_input(
            "Part number",
            value=st.session_state.search_input,
            placeholder=examples[0] if examples else "Enter part number",
            help=example_hint or "Enter the exact part identifier.",
            key="part_number_field",
        )
    with cols[1]:
        st.write("")
        st.write("")
        search_clicked = st.button("Search", type="primary", use_container_width=True)

    if examples:
        st.caption(example_hint)

    if search_clicked:
        st.session_state.search_input = part_input
        result = lookup_part(
            dataset,
            part_input,
            part_index=st.session_state.part_index,
        )
        st.session_state.lookup_result = result
        st.session_state.last_answer = None
        st.session_state.last_question = None
        if result.status == "found":
            st.session_state.selected_record = result.matches[0]
            st.session_state.selected_match_index = 0
        elif result.status == "duplicate":
            st.session_state.selected_record = None
            st.session_state.selected_match_index = 0
        else:
            st.session_state.selected_record = None

    result = st.session_state.lookup_result
    if result is None:
        return

    if result.status == "invalid_input":
        st.warning(result.message)
    elif result.status == "not_found":
        st.error(result.message)
    elif result.status == "duplicate":
        st.warning(result.message)
        _render_duplicate_selector(result.matches)
    elif result.status == "found":
        st.success(result.message)


def _render_duplicate_selector(matches: list[PartRecord]) -> None:
    st.markdown("**Matching records — select one:**")
    rows = []
    for i, match in enumerate(matches):
        row = {"#": i + 1, **match.display_fields()}
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    labels = []
    for i, match in enumerate(matches):
        bits = [
            f"{k}={v}"
            for k, v in list(match.populated_fields().items())[:4]
            if k != match.source.part_number_column
        ]
        labels.append(f"Record {i + 1}: " + "; ".join(bits))

    choice = st.radio("Intended record", labels, index=st.session_state.selected_match_index)
    idx = labels.index(choice)
    st.session_state.selected_match_index = idx
    st.session_state.selected_record = matches[idx]


def render_part_overview(record: PartRecord) -> None:
    st.markdown("#### B. Part Overview")
    st.markdown(
        f"**Selected part:** `{record.part_number}`  \n"
        f"**Source:** `{record.source.filename}` / `{record.source.sheet_name}`"
    )
    display = record.display_fields()
    table = pd.DataFrame(
        [{"Field": col, "Recorded value": display[col]} for col in record.original_columns]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    missing = [c for c, v in display.items() if v == "(not recorded)"]
    if missing:
        st.caption(
            "Empty cells are shown as `(not recorded)` — they are not treated as facts."
        )


def render_ask_ai(record: PartRecord, settings) -> None:
    st.markdown("#### C. Ask AI")
    suggestions = suggested_questions(record)
    if suggestions:
        st.caption("Suggested questions (based on available columns):")
        sug_cols = st.columns(min(len(suggestions), 4))
        for i, suggestion in enumerate(suggestions):
            with sug_cols[i]:
                if st.button(suggestion, key=f"sug_{i}", use_container_width=True):
                    st.session_state.question_area = suggestion
                    st.rerun()

    question = st.text_area(
        "Your question",
        placeholder="Ask about the selected part's Excel manufacturing record…",
        height=100,
        key="question_area",
    )

    submit = st.button("Submit question", type="primary")
    if submit:
        _handle_question(record, question, settings)


def _handle_question(record: PartRecord, question: str, settings) -> None:
    routed = route_question(question, record)

    cache_key = f"{record.part_number}::{record.source.row_index}::{question.strip()}"
    if st.session_state.last_question == cache_key and st.session_state.last_answer is not None:
        return

    if not routed.needs_llm:
        payload = direct_answer_payload(record, routed)
        try:
            validated = validate_answer(payload, record, used_llm=False)
        except ValidationError as exc:
            validated = build_fallback_answer(record, exc.message)
        st.session_state.last_answer = validated
        st.session_state.last_question = cache_key
        return

    if not settings.llm_ready:
        populated = record.populated_fields()
        lines = [
            "AI analysis is unavailable because the AI service is not configured.",
            "Here are the fields present in the selected Excel record:",
        ]
        for col, val in populated.items():
            lines.append(f"- {col}: {val}")
        if not populated:
            lines.append("- (no populated fields)")
        validated = build_fallback_answer(
            record,
            "\n".join(lines),
            status=AnswerStatus.ERROR,
            limitations=[
                "Configure the AI API key and model in your .env file to enable AI answers."
            ],
        )
        validated.evidence = [
            EvidenceItem(
                column=col,
                value=val,
                source_filename=record.source.filename,
                sheet_name=record.source.sheet_name,
                part_number=record.part_number,
            )
            for col, val in populated.items()
        ]
        st.session_state.last_answer = validated
        st.session_state.last_question = cache_key
        return

    with st.spinner("Analyzing the verified Excel record…"):
        client = OpenRouterClient(settings)
        try:
            payload = client.answer_question(record, question, routed)
            validated = validate_answer(payload, record, used_llm=True)
        except LLMServiceError as exc:
            validated = build_fallback_answer(
                record,
                f"AI-generated analysis could not be completed: {exc.message}",
                status=AnswerStatus.ERROR,
            )
        except ValidationError as exc:
            validated = build_fallback_answer(
                record,
                f"The model response could not be validated: {exc.message}",
                status=AnswerStatus.ERROR,
            )

    st.session_state.last_answer = validated
    st.session_state.last_question = cache_key


def render_answer(answer: ValidatedAnswer) -> None:
    st.markdown("#### D. AI Answer")
    status = answer.status.value
    status_class = {
        "answered": "cpi-status-answered",
        "partially_answered": "cpi-status-partial",
        "not_found": "cpi-status-missing",
        "error": "cpi-status-missing",
        "unsupported": "cpi-status-partial",
    }.get(status, "cpi-status-partial")

    st.markdown(
        f"**Status:** <span class='{status_class}'>{status}</span>"
        f"{' · AI' if answer.used_llm else ' · Direct'}",
        unsafe_allow_html=True,
    )
    st.markdown(answer.answer)

    st.markdown("**Evidence**")
    st.markdown(
        f"- Source: `{answer.source.filename}`  \n"
        f"- Sheet: `{answer.source.sheet_name}`  \n"
        f"- Part number: `{answer.source.part_number}`  \n"
        f"- Part-number column: `{answer.source.part_number_column}`"
    )
    if answer.evidence:
        for item in answer.evidence:
            st.markdown(
                f"<div class='cpi-evidence-item'>"
                f"<strong>Field:</strong> <span class='cpi-mono'>{item.column}</span><br>"
                f"<strong>Recorded value:</strong> {item.value}"
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No field-level evidence was attached to this response.")

    if answer.missing_information:
        st.markdown("**Missing information**")
        for item in answer.missing_information:
            st.markdown(f"- {item}")

    if answer.limitations:
        st.markdown("**Limitations**")
        for item in answer.limitations:
            st.markdown(f"- {item}")

    if answer.validation_notes:
        with st.expander("Validation notes"):
            for note in answer.validation_notes:
                st.markdown(f"- {note}")


def render_data_source(dataset: LoadedDataset, record: PartRecord | None) -> None:
    st.markdown("#### E. Data Source")
    st.markdown(
        f"- Workbook: `{dataset.filename}`  \n"
        f"- Sheet: `{dataset.sheet_name}`  \n"
        f"- Loaded records: **{dataset.record_count}**  \n"
        f"- Unique valid part identifiers: **{dataset.unique_part_count}**  \n"
        f"- Selected record: "
        f"**{record.part_number if record else '(none)'}**"
    )


def main() -> None:
    init_session_state()
    settings = get_settings()
    render_header()
    render_sidebar(settings)

    dataset: LoadedDataset | None = st.session_state.dataset
    if dataset is None:
        st.info(
            "Upload a manufacturing workbook from the sidebar to begin. "
            "Supported formats: `.xlsx`, `.xls`, `.csv`."
        )
        return

    with st.container():
        st.markdown('<div class="cpi-panel">', unsafe_allow_html=True)
        render_part_search(dataset)
        st.markdown("</div>", unsafe_allow_html=True)

    record: PartRecord | None = st.session_state.selected_record

    if record is not None:
        with st.container():
            render_part_overview(record)
        with st.container():
            render_ask_ai(record, settings)
        if st.session_state.last_answer is not None:
            with st.container():
                render_answer(st.session_state.last_answer)

    render_data_source(dataset, record)


if __name__ == "__main__":
    main()
