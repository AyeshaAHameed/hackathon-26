"""Tests for Excel/CSV loading and normalization."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from cnc_intelligence.data_loader import (
    DataLoadError,
    list_sheet_names,
    load_dataset,
    normalize_part_identifier,
)


def test_load_valid_xlsx(xlsx_bytes: bytes) -> None:
    ds = load_dataset(
        xlsx_bytes,
        filename="records.xlsx",
        sheet_name="Sheet1",
        part_number_column="Part Number",
    )
    assert ds.record_count == 5
    assert ds.part_number_column == "Part Number"
    assert "Material" in ds.original_columns


def test_load_valid_csv(csv_bytes: bytes) -> None:
    ds = load_dataset(
        csv_bytes,
        filename="records.csv",
        part_number_column="Part Number",
    )
    assert ds.sheet_name == "CSV"
    assert ds.record_count == 5


def test_empty_workbook(tmp_path: Path) -> None:
    path = tmp_path / "empty.xlsx"
    # Workbook with an empty sheet (no headers)
    from openpyxl import Workbook

    wb = Workbook()
    wb.save(path)
    with pytest.raises(DataLoadError) as exc:
        load_dataset(path, filename="empty.xlsx")
    assert exc.value.code in {"empty_sheet", "missing_headers"}


def test_missing_headers(tmp_path: Path) -> None:
    path = tmp_path / "no_headers.xlsx"
    # Empty header cells → pandas exposes Unnamed columns → missing_headers.
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append([None, None])
    ws.append([1, 2])
    ws.append([3, 4])
    wb.save(path)
    with pytest.raises(DataLoadError) as exc:
        load_dataset(path.read_bytes(), filename="no_headers.xlsx")
    assert exc.value.code == "missing_headers"


def test_missing_part_number_column(tmp_path: Path) -> None:
    path = tmp_path / "nopn.xlsx"
    pd.DataFrame({"Foo": [1], "Bar": [2]}).to_excel(path, index=False)
    with pytest.raises(DataLoadError) as exc:
        load_dataset(
            path.read_bytes(),
            filename="nopn.xlsx",
            part_number_column=None,
        )
    assert exc.value.code == "missing_part_number_column"


def test_multiple_sheets(xlsx_bytes: bytes) -> None:
    sheets = list_sheet_names(xlsx_bytes, "records.xlsx")
    assert "Sheet1" in sheets
    assert "Alt" in sheets
    ds = load_dataset(
        xlsx_bytes,
        filename="records.xlsx",
        sheet_name="Alt",
        part_number_column="Part No",
    )
    assert ds.sheet_name == "Alt"
    assert ds.record_count == 1


def test_empty_cells_preserved(xlsx_bytes: bytes) -> None:
    # Add a row with empty material via a custom workbook
    df = pd.DataFrame(
        [
            {"Part Number": "1", "Material": "Steel"},
            {"Part Number": "2", "Material": ""},
        ]
    )
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    ds = load_dataset(
        buf.getvalue(),
        filename="cells.xlsx",
        part_number_column="Part Number",
    )
    row = ds.dataframe[ds.dataframe["Part Number"] == "2"].iloc[0]
    assert (
        row["Material"] == ""
        or row["Material"] is None
        or pd.isna(row["Material"])
        or row["Material"] == ""
    )


def test_numeric_part_number_float_normalization() -> None:
    assert normalize_part_identifier(2280.0) == "2280"
    assert normalize_part_identifier("2280.0") == "2280"
    assert normalize_part_identifier(2280) == "2280"


def test_leading_zero_identifiers_preserved() -> None:
    assert normalize_part_identifier("00123") == "00123"
    assert normalize_part_identifier("123") == "123"
    assert normalize_part_identifier("00123") != normalize_part_identifier("123")


def test_duplicate_column_names(tmp_path: Path) -> None:
    # CSV path exercises our duplicate-header renaming (pandas Excel often
    # pre-uniquifies as Material.1 before our loader runs).
    csv_text = "Part Number,Material,Material\n2280,Steel,Extra\n"
    path = tmp_path / "dup.csv"
    path.write_text(csv_text, encoding="utf-8")
    ds = load_dataset(path, filename="dup.csv", part_number_column="Part Number")
    assert "Material" in ds.original_columns
    assert any(c.startswith("Material") for c in ds.original_columns)
    assert len(ds.original_columns) == len(set(ds.original_columns))
    assert ds.warnings  # duplicate rename warning expected


def test_unsupported_format() -> None:
    with pytest.raises(DataLoadError) as exc:
        load_dataset(b"not a real file", filename="notes.txt")
    assert exc.value.code == "unsupported_format"


def test_whitespace_trimmed_in_identifier() -> None:
    assert normalize_part_identifier("  2280  ") == "2280"
