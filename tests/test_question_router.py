"""Tests for question routing and field identification."""

from __future__ import annotations

from cnc_intelligence.models import QuestionCategory
from cnc_intelligence.question_router import route_question, suggested_questions


def test_question_asks_for_existing_field(sample_record) -> None:
    routed = route_question("What material is used?", sample_record)
    assert routed.category == QuestionCategory.FIELD_LOOKUP
    assert "Material" in routed.matched_columns
    assert routed.needs_llm is False
    assert routed.direct_answer_hint is not None
    assert "Aluminum 6061-T6" in routed.direct_answer_hint


def test_question_asks_for_missing_field(sample_record) -> None:
    routed = route_question("What is the cycle time?", sample_record)
    assert routed.category == QuestionCategory.FIELD_LOOKUP
    assert routed.needs_llm is False
    assert routed.direct_answer_hint is not None
    assert "does not contain" in routed.direct_answer_hint.lower()


def test_general_summary_question(sample_record) -> None:
    routed = route_question("Summarize the manufacturing record.", sample_record)
    assert routed.category == QuestionCategory.SUMMARY
    assert routed.needs_llm is True
    assert len(routed.matched_columns) > 0


def test_pdf_or_iges_unsupported(sample_record) -> None:
    routed = route_question("What tolerances are shown on the PDF drawing?", sample_record)
    assert routed.category == QuestionCategory.PDF_OR_IGES
    assert routed.needs_llm is False
    assert "Level 1" in routed.message


def test_iges_question(sample_record) -> None:
    routed = route_question("Extract the bounding box from the IGES model.", sample_record)
    assert routed.category == QuestionCategory.PDF_OR_IGES


def test_unrelated_question(sample_record) -> None:
    routed = route_question("What is the capital of France?", sample_record)
    assert routed.category == QuestionCategory.UNRELATED
    assert routed.needs_llm is False


def test_suggested_questions_use_available_columns(sample_record) -> None:
    suggestions = suggested_questions(sample_record)
    assert suggestions
    assert any("available" in s.lower() or "summarize" in s.lower() for s in suggestions)
