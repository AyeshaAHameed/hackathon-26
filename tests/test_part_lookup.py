"""Tests for exact part-number lookup."""

from __future__ import annotations

import io

import pandas as pd

from cnc_intelligence.data_loader import load_dataset
from cnc_intelligence.part_lookup import lookup_part


def test_existing_part_number(loaded_dataset) -> None:
    result = lookup_part(loaded_dataset, "2280")
    assert result.status == "found"
    assert len(result.matches) == 1
    assert result.matches[0].fields["Material"] == "Aluminum 6061-T6"


def test_nonexistent_part_number(loaded_dataset) -> None:
    result = lookup_part(loaded_dataset, "99999")
    assert result.status == "not_found"
    assert result.matches == []


def test_whitespace_around_identifiers(loaded_dataset) -> None:
    result = lookup_part(loaded_dataset, "  2280  ")
    assert result.status == "found"
    assert result.part_number == "2280"


def test_duplicate_matching_part_numbers(loaded_dataset) -> None:
    result = lookup_part(loaded_dataset, "9901")
    assert result.status == "duplicate"
    assert len(result.matches) == 2


def test_no_accidental_match_leading_zeros(loaded_dataset) -> None:
    r1 = lookup_part(loaded_dataset, "00123")
    r2 = lookup_part(loaded_dataset, "123")
    assert r1.status == "found"
    assert r2.status == "found"
    assert r1.matches[0].fields["Description"] != r2.matches[0].fields["Description"]
    assert r1.part_number == "00123"
    assert r2.part_number == "123"


def test_missing_part_number_input(loaded_dataset) -> None:
    result = lookup_part(loaded_dataset, "")
    assert result.status == "invalid_input"
    result_none = lookup_part(loaded_dataset, None)
    assert result_none.status == "invalid_input"


def test_float_cell_part_number_lookup(tmp_path) -> None:
    """Excel numeric cells like 2280.0 must still match query '2280'."""
    df = pd.DataFrame(
        {
            "Part Number": [2280.0, 4500.0],
            "Material": ["Al", "Steel"],
        }
    )
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    ds = load_dataset(
        buf.getvalue(),
        filename="numeric.xlsx",
        part_number_column="Part Number",
    )
    result = lookup_part(ds, "2280")
    assert result.status == "found"
    assert result.matches[0].fields["Material"] == "Al"


def test_case_sensitive_string_ids(tmp_path) -> None:
    """String part IDs are matched exactly (case-sensitive by default)."""
    df = pd.DataFrame(
        {
            "Part Number": ["AbC", "abc"],
            "Material": ["X", "Y"],
        }
    )
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    ds = load_dataset(
        buf.getvalue(),
        filename="case.xlsx",
        part_number_column="Part Number",
    )
    upper = lookup_part(ds, "AbC")
    lower = lookup_part(ds, "abc")
    assert upper.status == "found"
    assert lower.status == "found"
    assert upper.matches[0].fields["Material"] == "X"
    assert lower.matches[0].fields["Material"] == "Y"
