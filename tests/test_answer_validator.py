"""Tests for evidence generation and answer validation."""

from __future__ import annotations

import pytest

from cnc_intelligence.answer_validator import (
    ValidationError,
    build_fallback_answer,
    validate_answer,
)
from cnc_intelligence.models import AnswerStatus


def test_valid_evidence(sample_record) -> None:
    payload = {
        "answer": "The material is Aluminum 6061-T6.",
        "status": "answered",
        "evidence": [{"column": "Material", "value": "Aluminum 6061-T6"}],
        "missing_information": [],
        "limitations": [],
    }
    result = validate_answer(payload, sample_record)
    assert result.status == AnswerStatus.ANSWERED
    assert len(result.evidence) == 1
    assert result.evidence[0].column == "Material"
    assert result.evidence[0].source_filename == sample_record.source.filename
    assert result.evidence[0].part_number == "2280"


def test_unknown_column_in_evidence(sample_record) -> None:
    payload = {
        "answer": "Invented field.",
        "status": "answered",
        "evidence": [{"column": "NotARealColumn", "value": "xyz"}],
        "missing_information": [],
        "limitations": [],
    }
    result = validate_answer(payload, sample_record)
    assert result.evidence == []
    assert any("unknown column" in n.lower() for n in result.validation_notes)


def test_incorrect_evidence_value(sample_record) -> None:
    payload = {
        "answer": "Wrong material claimed.",
        "status": "answered",
        "evidence": [{"column": "Material", "value": "Unobtanium"}],
        "missing_information": [],
        "limitations": [],
    }
    result = validate_answer(payload, sample_record)
    assert result.evidence == []
    assert any("does not match" in n.lower() for n in result.validation_notes)


def test_missing_required_response_fields(sample_record) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_answer({"status": "answered"}, sample_record)
    assert exc.value.code == "empty_answer"


def test_malformed_status(sample_record) -> None:
    with pytest.raises(ValidationError):
        validate_answer(
            {"answer": "ok", "status": "totally_invalid"},
            sample_record,
        )


def test_empty_answer_rejected(sample_record) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_answer(
            {"answer": "   ", "status": "answered"},
            sample_record,
        )
    assert exc.value.code == "empty_answer"


def test_authoritative_source_metadata(sample_record) -> None:
    payload = {
        "answer": "Material recorded.",
        "status": "answered",
        "evidence": [{"column": "Material", "value": "Aluminum 6061-T6"}],
        "missing_information": [],
        "limitations": [],
    }
    result = validate_answer(payload, sample_record)
    # Even if model tried to invent source info in evidence, we stamp authoritative meta
    assert result.source.filename == sample_record.source.filename
    assert result.source.sheet_name == sample_record.source.sheet_name
    assert result.evidence[0].sheet_name == sample_record.source.sheet_name


def test_fallback_answer(sample_record) -> None:
    result = build_fallback_answer(sample_record, "API unavailable")
    assert result.status == AnswerStatus.ERROR
    assert result.used_llm is False
    assert "API unavailable" in result.answer
