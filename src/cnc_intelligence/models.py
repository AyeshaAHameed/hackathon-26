"""Typed models for records, answers, evidence, and errors."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    PARTIALLY_ANSWERED = "partially_answered"
    NOT_FOUND = "not_found"
    ERROR = "error"
    UNSUPPORTED = "unsupported"


class QuestionCategory(StrEnum):
    FIELD_LOOKUP = "field_lookup"
    SUMMARY = "summary"
    MISSING_CHECK = "missing_check"
    PDF_OR_IGES = "pdf_or_iges"
    UNRELATED = "unrelated"
    GENERAL = "general"


class EvidenceItem(BaseModel):
    """A single fact supported by the retrieved Excel record."""

    column: str
    value: str
    source_filename: str
    sheet_name: str
    part_number: str


class SourceMetadata(BaseModel):
    """Authoritative source metadata generated in Python (not by the LLM)."""

    filename: str
    sheet_name: str
    part_number: str
    part_number_column: str
    record_count: int = 0
    unique_part_count: int = 0
    row_index: int | None = None


class PartRecord(BaseModel):
    """A single manufacturing record retrieved by exact part-number match."""

    part_number: str
    fields: dict[str, Any]
    source: SourceMetadata
    original_columns: list[str]

    def display_fields(self) -> dict[str, str]:
        """Return field values as display strings, marking missing values."""
        result: dict[str, str] = {}
        for col, val in self.fields.items():
            if val is None or (isinstance(val, float) and val != val):  # NaN
                result[col] = "(not recorded)"
            elif isinstance(val, str) and val.strip() == "":
                result[col] = "(not recorded)"
            else:
                result[col] = str(val)
        return result

    def populated_fields(self) -> dict[str, str]:
        """Return only fields with non-empty recorded values."""
        return {
            col: display
            for col, display in self.display_fields().items()
            if display != "(not recorded)"
        }


class LLMAnswerPayload(BaseModel):
    """Structured payload expected from the LLM."""

    answer: str
    status: AnswerStatus
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ValidatedAnswer(BaseModel):
    """Answer after Python-side evidence validation and metadata injection."""

    answer: str
    status: AnswerStatus
    evidence: list[EvidenceItem] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source: SourceMetadata
    used_llm: bool = True
    validation_notes: list[str] = Field(default_factory=list)


class LookupResult(BaseModel):
    """Result of an exact part-number lookup."""

    status: str  # found | not_found | duplicate | invalid_input
    part_number: str
    matches: list[PartRecord] = Field(default_factory=list)
    message: str = ""


class DatasetInfo(BaseModel):
    """Summary of a loaded manufacturing dataset."""

    filename: str
    sheet_name: str
    columns: list[str]
    part_number_column: str
    record_count: int
    unique_part_count: int
    part_number_candidates: list[str] = Field(default_factory=list)
    sheet_names: list[str] = Field(default_factory=list)


class AppError(BaseModel):
    """User-facing application error."""

    code: str
    message: str
    details: str | None = None
