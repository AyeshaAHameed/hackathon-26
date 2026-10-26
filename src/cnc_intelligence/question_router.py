"""Classify questions and identify relevant available fields."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cnc_intelligence.models import PartRecord, QuestionCategory
from cnc_intelligence.schema_detector import normalize_column_name

# Keywords that strongly indicate PDF / IGES requirements (Level 2/3).
_PDF_IGES_PATTERNS = [
    r"\bpdf\b",
    r"\bdrawing\b",
    r"\bblueprint\b",
    r"\bprint\b",
    r"\biges\b",
    r"\b\.igs\b",
    r"\b\.iges\b",
    r"\bcad\b",
    r"\b3d\s*model\b",
    r"\bgeometry\b",
    r"\bsolid\s*model\b",
    r"\btolerance\s*stack",
    r"\bgdt\b",
    r"\bgd&t\b",
    r"\bdimensioned\s*drawing\b",
]

_SUMMARY_PATTERNS = [
    r"\bsummar",
    r"\boverview\b",
    r"\bwhat\s+is\s+this\s+part\b",
    r"\btell\s+me\s+about\b",
    r"\bdescribe\b",
    r"\bwhat\s+information\s+is\s+available\b",
    r"\bavailable\s+about\b",
    r"\ball\s+fields\b",
    r"\bmanufacturing\s+record\b",
]

_MISSING_CHECK_PATTERNS = [
    r"\bis\s+(the\s+)?(required\s+)?information\s+available\b",
    r"\bdo\s+we\s+have\b",
    r"\bis\s+.+\s+recorded\b",
    r"\bmissing\b",
    r"\bnot\s+available\b",
    r"\bcontain\b",
]

_UNRELATED_PATTERNS = [
    r"\bweather\b",
    r"\bjoke\b",
    r"\brecipe\b",
    r"\bcapital\s+of\b",
    r"\bwho\s+won\b",
    r"\bstock\s+price\b",
    r"\bwrite\s+(me\s+)?(a\s+)?poem\b",
]

# Common engineering terms mapped to likely column name fragments.
_FIELD_HINTS: dict[str, list[str]] = {
    "material": ["material", "mat", "alloy", "steel", "aluminum"],
    "process": ["process", "operation", "op", "machining", "method"],
    "machine": ["machine", "cnc", "equipment", "workcenter", "work centre"],
    "dimension": ["dimension", "size", "length", "width", "height", "diameter", "od", "id"],
    "tolerance": ["tolerance", "tol"],
    "quantity": ["quantity", "qty", "count"],
    "description": ["description", "desc", "name", "title"],
    "cost": ["cost", "price", "rate"],
    "cycle": ["cycle", "time", "duration"],
    "supplier": ["supplier", "vendor"],
    "revision": ["revision", "rev", "version"],
    "status": ["status", "state"],
}


@dataclass
class RoutedQuestion:
    """Result of classifying a user question against a part record."""

    category: QuestionCategory
    question: str
    matched_columns: list[str] = field(default_factory=list)
    missing_topics: list[str] = field(default_factory=list)
    needs_llm: bool = True
    direct_answer_hint: str | None = None
    message: str = ""


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def _find_columns_for_question(question: str, columns: list[str]) -> list[str]:
    """Find columns whose names appear in or are hinted by the question."""
    q_norm = normalize_column_name(question)
    matched: list[str] = []

    for col in columns:
        col_norm = normalize_column_name(col)
        # Direct mention of column name (as whole words / phrase)
        if col_norm and col_norm in q_norm:
            matched.append(col)
            continue
        # Token overlap for multi-word columns
        tokens = [t for t in re.split(r"[_\s\-]+", col_norm) if len(t) > 2]
        if tokens and all(t in q_norm for t in tokens):
            matched.append(col)

    # Hint-based matching
    for topic, hints in _FIELD_HINTS.items():
        if any(h in q_norm for h in hints) or topic in q_norm:
            for col in columns:
                col_norm = normalize_column_name(col)
                if any(h in col_norm for h in hints) or topic in col_norm:
                    if col not in matched:
                        matched.append(col)

    return matched


def _topics_requested(question: str) -> list[str]:
    q_norm = normalize_column_name(question)
    topics: list[str] = []
    for topic, hints in _FIELD_HINTS.items():
        if topic in q_norm or any(h in q_norm for h in hints):
            topics.append(topic)
    return topics


def route_question(question: str, record: PartRecord) -> RoutedQuestion:
    """
    Classify the question and identify relevant fields from the selected record.
    """
    cleaned = (question or "").strip()
    if not cleaned:
        return RoutedQuestion(
            category=QuestionCategory.UNRELATED,
            question="",
            needs_llm=False,
            message="Please enter a question about the selected part's manufacturing record.",
        )

    columns = record.original_columns
    populated = record.populated_fields()

    if _matches_any(cleaned, _PDF_IGES_PATTERNS):
        return RoutedQuestion(
            category=QuestionCategory.PDF_OR_IGES,
            question=cleaned,
            needs_llm=False,
            message=(
                "PDF drawing and IGES 3D model analysis are not implemented in Level 1. "
                "This version answers questions using the Excel manufacturing record only. "
                "PDF (Level 2) and IGES (Level 3) support are planned future enhancements."
            ),
            missing_topics=["PDF/IGES analysis"],
        )

    if _matches_any(cleaned, _UNRELATED_PATTERNS):
        return RoutedQuestion(
            category=QuestionCategory.UNRELATED,
            question=cleaned,
            needs_llm=False,
            message=(
                "This question is outside the scope of CNC Part Intelligence Level 1. "
                "Ask about the selected part's Excel manufacturing record."
            ),
        )

    matched_columns = _find_columns_for_question(cleaned, columns)
    topics = _topics_requested(cleaned)

    if _matches_any(cleaned, _SUMMARY_PATTERNS):
        return RoutedQuestion(
            category=QuestionCategory.SUMMARY,
            question=cleaned,
            matched_columns=list(populated.keys()),
            needs_llm=True,
            message="Summary request — will use available record fields.",
        )

    if _matches_any(cleaned, _MISSING_CHECK_PATTERNS) and not matched_columns:
        return RoutedQuestion(
            category=QuestionCategory.MISSING_CHECK,
            question=cleaned,
            matched_columns=list(populated.keys()),
            needs_llm=True,
            message="Availability check against the Excel record.",
        )

    # Field lookup: question targets specific columns
    if matched_columns:
        present = [c for c in matched_columns if c in populated]
        absent = [c for c in matched_columns if c not in populated]
        missing_topics = [
            t for t in topics if not any(t in normalize_column_name(c) for c in present)
        ]

        if present and not absent and len(present) == 1:
            col = present[0]
            value = populated[col]
            return RoutedQuestion(
                category=QuestionCategory.FIELD_LOOKUP,
                question=cleaned,
                matched_columns=present,
                missing_topics=missing_topics,
                needs_llm=False,
                direct_answer_hint=(
                    f"According to the Excel manufacturing record, "
                    f"'{col}' is recorded as '{value}'."
                ),
                message="Direct field lookup from the selected record.",
            )

        if not present and (absent or missing_topics):
            label = ", ".join(absent or missing_topics)
            return RoutedQuestion(
                category=QuestionCategory.FIELD_LOOKUP,
                question=cleaned,
                matched_columns=[],
                missing_topics=absent or missing_topics,
                needs_llm=False,
                direct_answer_hint=(
                    f"The Excel manufacturing record for part '{record.part_number}' "
                    f"does not contain information about: {label}."
                ),
                message="Requested field(s) not present in the record.",
            )

        return RoutedQuestion(
            category=QuestionCategory.FIELD_LOOKUP,
            question=cleaned,
            matched_columns=matched_columns,
            missing_topics=missing_topics or absent,
            needs_llm=True,
            message="Multi-field question — using LLM with grounded record context.",
        )

    # Topic requested but no matching column at all
    if topics:
        return RoutedQuestion(
            category=QuestionCategory.FIELD_LOOKUP,
            question=cleaned,
            matched_columns=[],
            missing_topics=topics,
            needs_llm=False,
            direct_answer_hint=(
                f"The Excel manufacturing record for part '{record.part_number}' "
                f"does not contain information about: {', '.join(topics)}. "
                f"Available columns: {', '.join(columns)}."
            ),
            message="Requested topic not present in available columns.",
        )

    # General manufacturing question — let the LLM answer from the record
    return RoutedQuestion(
        category=QuestionCategory.GENERAL,
        question=cleaned,
        matched_columns=list(populated.keys()),
        needs_llm=True,
        message="General question — grounded against the full selected record.",
    )


def suggested_questions(record: PartRecord, limit: int = 4) -> list[str]:
    """Derive example questions from columns that actually exist."""
    suggestions: list[str] = [
        "What information is available about this component?",
        "Summarize the manufacturing record.",
    ]
    populated = record.populated_fields()
    for col in populated:
        col_norm = normalize_column_name(col)
        if "material" in col_norm:
            suggestions.append(f"What is the value recorded in '{col}'?")
        elif "process" in col_norm or "operation" in col_norm:
            suggestions.append(f"What manufacturing process is recorded in '{col}'?")
        elif "machine" in col_norm:
            suggestions.append(f"Which machine is associated with this part ({col})?")
        elif "dimension" in col_norm or any(
            d in col_norm for d in ("length", "width", "height", "diameter")
        ):
            suggestions.append(f"What are the recorded dimensions ({col})?")
        elif "description" in col_norm:
            suggestions.append("What is this part?")

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique[:limit]
