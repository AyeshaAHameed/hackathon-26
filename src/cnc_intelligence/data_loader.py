"""Workbook and CSV loading, validation, and safe normalization."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from cnc_intelligence.schema_detector import (
    auto_select_part_number_column,
    suggest_part_number_columns,
)

SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv"}


class DataLoadError(Exception):
    """Raised when a manufacturing dataset cannot be loaded or validated."""

    def __init__(self, message: str, code: str = "data_load_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class LoadedDataset:
    """In-memory manufacturing dataset ready for part lookup."""

    filename: str
    sheet_name: str
    dataframe: pd.DataFrame
    original_columns: list[str]
    part_number_column: str
    sheet_names: list[str] = field(default_factory=list)
    part_number_candidates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def record_count(self) -> int:
        return len(self.dataframe)

    @property
    def unique_part_count(self) -> int:
        series = self.dataframe[self.part_number_column]
        return int(series.nunique(dropna=True))


def _extension_of(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_extension(filename: str) -> str:
    ext = _extension_of(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise DataLoadError(
            f"Unsupported file format '{ext or '(none)'}'. "
            f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.",
            code="unsupported_format",
        )
    return ext


def validate_upload_size(size_bytes: int, max_bytes: int) -> None:
    if size_bytes > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        raise DataLoadError(
            f"File exceeds the maximum upload size of {max_mb:.0f} MB.",
            code="file_too_large",
        )


def list_sheet_names(source: Path | BinaryIO | bytes, filename: str) -> list[str]:
    """Return sheet names for Excel workbooks. CSV returns a single synthetic name."""
    ext = validate_extension(filename)
    if ext == ".csv":
        return ["CSV"]

    try:
        if isinstance(source, bytes):
            buffer = io.BytesIO(source)
            xl = pd.ExcelFile(buffer, engine=_excel_engine(ext))
        elif isinstance(source, Path):
            xl = pd.ExcelFile(source, engine=_excel_engine(ext))
        else:
            xl = pd.ExcelFile(source, engine=_excel_engine(ext))
        names = list(xl.sheet_names)
        if not names:
            raise DataLoadError("The workbook contains no sheets.", code="empty_workbook")
        return names
    except DataLoadError:
        raise
    except Exception as exc:
        raise DataLoadError(
            f"Unable to read workbook sheets: {exc}",
            code="unreadable_workbook",
        ) from exc


def _excel_engine(ext: str) -> str:
    if ext == ".xlsx":
        return "openpyxl"
    if ext == ".xls":
        return "xlrd"
    raise DataLoadError(f"No Excel engine for extension {ext}", code="unsupported_format")


def normalize_part_identifier(value: object) -> str | None:
    """
    Normalize a part-number cell value for exact matching.

    - Preserves leading zeros when the source provides them as text.
    - Converts Excel float representations like 2280.0 to '2280'.
    - Trims surrounding whitespace.
    - Does not treat '00123' and '123' as identical.
    - Returns None for missing / empty values.
    """
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return None
    # Handle stringified floats from mixed-type columns, e.g. "2280.0"
    if re_fullmatch_float(text):
        try:
            as_float = float(text)
            if as_float.is_integer():
                # Only normalize .0 floats — do not strip leading zeros from
                # strings that are not float-like (e.g. "00123" stays "00123").
                return str(int(as_float))
        except ValueError:
            pass
    return text


def re_fullmatch_float(text: str) -> bool:
    """Return True if text looks like a decimal float (e.g. 2280.0), not an ID."""
    return bool(re.fullmatch(r"-?\d+\.0+", text))


def _dedupe_column_names(columns: list[str]) -> tuple[list[str], list[str]]:
    """Ensure unique column names; return (unique_names, warnings)."""
    seen: dict[str, int] = {}
    result: list[str] = []
    warnings: list[str] = []
    for col in columns:
        name = str(col) if col is not None else ""
        if name.strip() == "" or name.startswith("Unnamed:"):
            name = f"Column_{len(result) + 1}"
            warnings.append(f"Renamed blank/unnamed header to '{name}'.")
        if name in seen:
            seen[name] += 1
            new_name = f"{name}_{seen[name]}"
            warnings.append(f"Duplicate column '{name}' renamed to '{new_name}'.")
            result.append(new_name)
        else:
            seen[name] = 0
            result.append(name)

    # Pandas often pre-uniquifies duplicates as "Name.1", "Name.2" before we see them.
    for name in result:
        match = re.fullmatch(r"(.+)\.(\d+)", name)
        if match and match.group(1) in result:
            warnings.append(
                f"Detected duplicate-derived column '{name}' "
                f"(base column '{match.group(1)}' also present)."
            )
    return result, warnings


def _read_raw_dataframe(
    source: Path | BinaryIO | bytes,
    filename: str,
    sheet_name: str | int | None,
) -> tuple[pd.DataFrame, str, list[str]]:
    """Read a raw DataFrame and return (df, resolved_sheet_name, all_sheet_names)."""
    ext = validate_extension(filename)

    if ext == ".csv":
        try:
            if isinstance(source, bytes):
                df = pd.read_csv(io.BytesIO(source), dtype=object, keep_default_na=False)
            elif isinstance(source, Path):
                df = pd.read_csv(source, dtype=object, keep_default_na=False)
            else:
                df = pd.read_csv(source, dtype=object, keep_default_na=False)
        except Exception as exc:
            raise DataLoadError(
                f"Unable to read CSV file: {exc}",
                code="unreadable_workbook",
            ) from exc
        return df, "CSV", ["CSV"]

    sheets = list_sheet_names(source, filename)
    resolved = sheet_name if sheet_name is not None else sheets[0]
    if isinstance(resolved, str) and resolved not in sheets:
        raise DataLoadError(
            f"Sheet '{resolved}' not found. Available sheets: {', '.join(sheets)}.",
            code="sheet_not_found",
        )

    try:
        engine = _excel_engine(ext)
        # Re-open stream if needed
        if isinstance(source, bytes):
            buffer = io.BytesIO(source)
            df = pd.read_excel(
                buffer,
                sheet_name=resolved,
                dtype=object,
                engine=engine,
                keep_default_na=False,
            )
        elif isinstance(source, Path):
            df = pd.read_excel(
                source,
                sheet_name=resolved,
                dtype=object,
                engine=engine,
                keep_default_na=False,
            )
        else:
            # BinaryIO may have been consumed by list_sheet_names; seek if possible
            if hasattr(source, "seek"):
                source.seek(0)
            df = pd.read_excel(
                source,
                sheet_name=resolved,
                dtype=object,
                engine=engine,
                keep_default_na=False,
            )
    except DataLoadError:
        raise
    except Exception as exc:
        raise DataLoadError(
            f"Unable to read sheet '{resolved}': {exc}",
            code="unreadable_workbook",
        ) from exc

    sheet_label = resolved if isinstance(resolved, str) else sheets[resolved]
    return df, sheet_label, sheets


def load_dataset(
    source: Path | BinaryIO | bytes,
    filename: str,
    *,
    sheet_name: str | int | None = None,
    part_number_column: str | None = None,
    max_bytes: int | None = None,
) -> LoadedDataset:
    """
    Load and validate a manufacturing workbook or CSV.

    Raises DataLoadError with actionable messages on validation failure.
    """
    validate_extension(filename)

    if max_bytes is not None:
        if isinstance(source, bytes) and len(source) > max_bytes:
            validate_upload_size(len(source), max_bytes)
        elif isinstance(source, Path) and source.exists():
            validate_upload_size(source.stat().st_size, max_bytes)

    if isinstance(source, Path) and not source.exists():
        raise DataLoadError(
            f"File not found: {source.name}",
            code="file_not_found",
        )

    df, resolved_sheet, sheet_names = _read_raw_dataframe(source, filename, sheet_name)

    if df.empty and len(df.columns) == 0:
        raise DataLoadError(
            "The selected sheet is empty (no headers or data).",
            code="empty_sheet",
        )

    if len(df.columns) == 0:
        raise DataLoadError(
            "The selected sheet has no column headers.",
            code="missing_headers",
        )

    # Detect entirely empty header row (all Unnamed)
    if all(str(c).startswith("Unnamed:") for c in df.columns):
        raise DataLoadError(
            "The selected sheet appears to be missing headers.",
            code="missing_headers",
        )

    original_raw = [str(c) for c in df.columns]
    unique_cols, warnings = _dedupe_column_names(original_raw)
    df.columns = unique_cols

    # Drop fully empty rows
    df = df.replace("", pd.NA)
    df = df.dropna(how="all").reset_index(drop=True)
    df = df.fillna("")

    if df.empty:
        raise DataLoadError(
            "The selected sheet has headers but no data rows.",
            code="empty_sheet",
        )

    candidates = suggest_part_number_columns(unique_cols)

    if part_number_column is None:
        part_number_column = auto_select_part_number_column(unique_cols)

    if part_number_column is None:
        raise DataLoadError(
            "Could not determine the part-number column. "
            f"Please select one. Suggested candidates: "
            f"{', '.join(candidates) if candidates else '(none found — choose manually)'}.",
            code="missing_part_number_column",
        )

    if part_number_column not in unique_cols:
        raise DataLoadError(
            f"Part-number column '{part_number_column}' not found in the sheet. "
            f"Available columns: {', '.join(unique_cols)}.",
            code="missing_part_number_column",
        )

    # Normalize part identifiers into a parallel index column (keep original too)
    normalized = df[part_number_column].map(normalize_part_identifier)
    empty_count = int(normalized.isna().sum())
    if empty_count == len(df):
        raise DataLoadError(
            f"All values in part-number column '{part_number_column}' are empty or invalid.",
            code="invalid_part_numbers",
        )
    if empty_count > 0:
        warnings.append(
            f"{empty_count} row(s) have empty/invalid part numbers and will be skipped during lookup."
        )

    # Attach normalized series for indexing (internal column)
    df = df.copy()
    df["__normalized_part_number__"] = normalized

    return LoadedDataset(
        filename=Path(filename).name,
        sheet_name=resolved_sheet,
        dataframe=df,
        original_columns=unique_cols,
        part_number_column=part_number_column,
        sheet_names=sheet_names,
        part_number_candidates=candidates,
        warnings=warnings,
    )


def load_from_path(
    path: Path | str,
    *,
    sheet_name: str | int | None = None,
    part_number_column: str | None = None,
) -> LoadedDataset:
    """Load a dataset from a local filesystem path."""
    path = Path(path)
    return load_dataset(
        path,
        filename=path.name,
        sheet_name=sheet_name,
        part_number_column=part_number_column,
    )


def discover_default_workbook(data_dir: Path) -> Path | None:
    """Find a default manufacturing workbook in the data directory."""
    if not data_dir.exists():
        return None
    preferred = [
        "sample_manufacturing_records.xlsx",
        "manufacturing_records.xlsx",
        "parts.xlsx",
    ]
    for name in preferred:
        candidate = data_dir / name
        if candidate.exists():
            return candidate
    # Any xlsx/xls/csv
    for pattern in ("*.xlsx", "*.xls", "*.csv"):
        matches = sorted(data_dir.glob(pattern))
        if matches:
            return matches[0]
    return None
