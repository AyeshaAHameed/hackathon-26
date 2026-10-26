"""Response validation and checks for unsupported claims."""

from __future__ import annotations

from typing import Any

from cnc_intelligence.models import (
    AnswerStatus,
    EvidenceItem,
    PartRecord,
    ValidatedAnswer,
)


class ValidationError(Exception):
    """Raised when an LLM response fails schema or evidence validation."""

    def __init__(self, message: str, code: str = "validation_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_VALID_STATUSES = {s.value for s in AnswerStatus}


def _coerce_status(raw: Any) -> AnswerStatus:
    if isinstance(raw, AnswerStatus):
        return raw
    if isinstance(raw, str) and raw in _VALID_STATUSES:
        return AnswerStatus(raw)
    # Map common variants
    if isinstance(raw, str):
        lowered = raw.strip().lower().replace(" ", "_")
        if lowered in _VALID_STATUSES:
            return AnswerStatus(lowered)
    raise ValidationError(
        f"Invalid or missing answer status: {raw!r}. "
        f"Expected one of: {', '.join(sorted(_VALID_STATUSES))}.",
        code="invalid_status",
    )


def _normalize_evidence_list(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError(
            "Evidence must be a list of objects with column and value.",
            code="invalid_evidence",
        )
    return [item for item in raw if isinstance(item, dict)]


def _value_matches(recorded: Any, cited: Any) -> bool:
    """Compare evidence values loosely but safely."""
    if recorded is None:
        recorded_str = "(not recorded)"
    else:
        recorded_str = str(recorded).strip()
    cited_str = str(cited).strip() if cited is not None else ""
    return recorded_str == cited_str


def validate_answer(
    payload: dict[str, Any],
    record: PartRecord,
    *,
    used_llm: bool = True,
) -> ValidatedAnswer:
    """
    Validate a structured answer payload against the selected record.

    Authoritative source metadata (filename, sheet, part number) is always
    taken from the Python-side PartRecord, never from the model.
    """
    if not isinstance(payload, dict):
        raise ValidationError(
            "Answer payload must be a JSON object.",
            code="invalid_schema",
        )

    answer_text = payload.get("answer")
    if not isinstance(answer_text, str) or answer_text.strip() == "":
        raise ValidationError(
            "Answer text is missing or empty.",
            code="empty_answer",
        )

    status = _coerce_status(payload.get("status"))

    missing_raw = payload.get("missing_information") or []
    if not isinstance(missing_raw, list):
        raise ValidationError(
            "missing_information must be a list.",
            code="invalid_schema",
        )
    missing_information = [str(m) for m in missing_raw]

    limitations_raw = payload.get("limitations") or []
    if not isinstance(limitations_raw, list):
        raise ValidationError(
            "limitations must be a list.",
            code="invalid_schema",
        )
    limitations = [str(item) for item in limitations_raw]

    notes: list[str] = []
    evidence_items: list[EvidenceItem] = []
    display = record.display_fields()
    raw_evidence = _normalize_evidence_list(payload.get("evidence"))

    for item in raw_evidence:
        column = item.get("column") or item.get("field") or item.get("name")
        value = item.get("value") or item.get("recorded_value")
        if not isinstance(column, str) or column.strip() == "":
            notes.append("Dropped evidence item with missing column name.")
            continue
        column = column.strip()

        if column not in record.fields and column not in display:
            notes.append(
                f"Rejected evidence for unknown column '{column}' "
                "(not present in the selected record)."
            )
            continue

        recorded_display = display.get(column, "(not recorded)")
        if value is not None and not _value_matches(recorded_display, value):
            # Also try matching against raw field value
            raw_val = record.fields.get(column)
            if not _value_matches(raw_val, value) and not _value_matches(
                recorded_display if recorded_display != "(not recorded)" else raw_val,
                value,
            ):
                notes.append(
                    f"Rejected evidence for column '{column}': "
                    f"cited value does not match the retrieved record."
                )
                continue

        # Always use authoritative recorded value
        authoritative_value = (
            recorded_display
            if recorded_display != "(not recorded)"
            else (str(value) if value is not None else "(not recorded)")
        )
        if recorded_display == "(not recorded)":
            notes.append(f"Skipped evidence for column '{column}' because the cell is empty.")
            continue

        evidence_items.append(
            EvidenceItem(
                column=column,
                value=authoritative_value,
                source_filename=record.source.filename,
                sheet_name=record.source.sheet_name,
                part_number=record.part_number,
            )
        )

    # If the model claimed "answered" but we stripped all evidence and there
    # are missing topics, downgrade status.
    if status == AnswerStatus.ANSWERED and not evidence_items and missing_information and used_llm:
        status = AnswerStatus.PARTIALLY_ANSWERED
        notes.append("Status adjusted to partially_answered after evidence validation.")

    return ValidatedAnswer(
        answer=answer_text.strip(),
        status=status,
        evidence=evidence_items,
        missing_information=missing_information,
        limitations=limitations,
        source=record.source,
        used_llm=used_llm,
        validation_notes=notes,
    )


def build_fallback_answer(
    record: PartRecord,
    message: str,
    *,
    status: AnswerStatus = AnswerStatus.ERROR,
    limitations: list[str] | None = None,
) -> ValidatedAnswer:
    """Build a safe answer when the LLM call fails, still showing the record."""
    return ValidatedAnswer(
        answer=message,
        status=status,
        evidence=[],
        missing_information=[],
        limitations=limitations
        or [
            "AI-generated analysis could not be completed. "
            "The Excel record below remains available for manual review."
        ],
        source=record.source,
        used_llm=False,
        validation_notes=[],
    )
