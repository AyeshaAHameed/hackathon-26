"""Exact part-number matching and record retrieval."""

from __future__ import annotations

from typing import Any

import pandas as pd

from cnc_intelligence.data_loader import LoadedDataset, normalize_part_identifier
from cnc_intelligence.models import LookupResult, PartRecord, SourceMetadata


def build_part_index(dataset: LoadedDataset) -> dict[str, list[int]]:
    """
    Build an exact-match index from normalized part numbers to row indices.

    Empty / invalid part numbers are excluded.
    """
    index: dict[str, list[int]] = {}
    series = dataset.dataframe["__normalized_part_number__"]
    for row_idx, part_id in series.items():
        if part_id is None or (isinstance(part_id, float) and pd.isna(part_id)):
            continue
        key = str(part_id)
        index.setdefault(key, []).append(int(row_idx))
    return index


def _row_to_fields(row: pd.Series, columns: list[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for col in columns:
        value = row[col]
        if value is None or (isinstance(value, float) and pd.isna(value)):
            fields[col] = None
        elif isinstance(value, str) and value.strip() == "":
            fields[col] = None
        else:
            # Prefer string form for identifiers / mixed cells
            if isinstance(value, float) and value.is_integer():
                fields[col] = str(int(value))
            else:
                fields[col] = value if not isinstance(value, str) else value
    return fields


def lookup_part(
    dataset: LoadedDataset,
    part_number: str | None,
    *,
    part_index: dict[str, list[int]] | None = None,
) -> LookupResult:
    """
    Perform exact part-number lookup.

    Does not silently pick the first duplicate — returns all matches when
    multiple rows share the same identifier.
    """
    if part_number is None or str(part_number).strip() == "":
        return LookupResult(
            status="invalid_input",
            part_number="",
            message="Please enter a part number.",
        )

    normalized = normalize_part_identifier(part_number)
    if normalized is None:
        return LookupResult(
            status="invalid_input",
            part_number=str(part_number).strip(),
            message="The entered part number is empty or invalid.",
        )

    index = part_index if part_index is not None else build_part_index(dataset)
    row_indices = index.get(normalized, [])

    if not row_indices:
        return LookupResult(
            status="not_found",
            part_number=normalized,
            message=(
                f"No manufacturing record found for part number '{normalized}'. "
                "Verify the part number and that the correct sheet and "
                "part-number column are selected."
            ),
        )

    matches: list[PartRecord] = []
    for row_idx in row_indices:
        row = dataset.dataframe.loc[row_idx]
        fields = _row_to_fields(row, dataset.original_columns)
        source = SourceMetadata(
            filename=dataset.filename,
            sheet_name=dataset.sheet_name,
            part_number=normalized,
            part_number_column=dataset.part_number_column,
            record_count=dataset.record_count,
            unique_part_count=dataset.unique_part_count,
            row_index=int(row_idx),
        )
        matches.append(
            PartRecord(
                part_number=normalized,
                fields=fields,
                source=source,
                original_columns=list(dataset.original_columns),
            )
        )

    if len(matches) > 1:
        return LookupResult(
            status="duplicate",
            part_number=normalized,
            matches=matches,
            message=(
                f"Part number '{normalized}' matches {len(matches)} records. "
                "Select the intended record using the distinguishing fields below."
            ),
        )

    return LookupResult(
        status="found",
        part_number=normalized,
        matches=matches,
        message=f"Found manufacturing record for part number '{normalized}'.",
    )


def select_match_by_index(result: LookupResult, match_index: int) -> PartRecord | None:
    """Select a specific match from a duplicate lookup result."""
    if match_index < 0 or match_index >= len(result.matches):
        return None
    return result.matches[match_index]


def example_part_numbers(dataset: LoadedDataset, limit: int = 5) -> list[str]:
    """Return a few example valid part numbers from the loaded dataset."""
    index = build_part_index(dataset)
    return list(index.keys())[:limit]
