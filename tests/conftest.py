"""Shared fixtures for CNC Part Intelligence tests."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from cnc_intelligence.config import Settings
from cnc_intelligence.data_loader import load_dataset
from cnc_intelligence.models import PartRecord


@pytest.fixture
def sample_rows() -> list[dict]:
    return [
        {
            "Part Number": "2280",
            "Description": "Flanged bearing housing",
            "Material": "Aluminum 6061-T6",
            "Process": "CNC milling",
            "Machine": "HAAS VF-2",
        },
        {
            "Part Number": "00123",
            "Description": "Spacer washer",
            "Material": "Brass C360",
            "Process": "CNC turning",
            "Machine": "Haas ST-10",
        },
        {
            "Part Number": "123",
            "Description": "Mounting bracket",
            "Material": "Mild steel",
            "Process": "CNC milling",
            "Machine": "DMG MORI NVX",
        },
        {
            "Part Number": "9901",
            "Description": "Adapter plate A",
            "Material": "Aluminum 7075",
            "Process": "CNC milling",
            "Machine": "Makino A51",
        },
        {
            "Part Number": "9901",
            "Description": "Adapter plate B",
            "Material": "Aluminum 7075",
            "Process": "CNC milling",
            "Machine": "Makino A51",
        },
    ]


@pytest.fixture
def xlsx_bytes(sample_rows: list[dict], tmp_path: Path) -> bytes:
    df = pd.DataFrame(sample_rows)
    path = tmp_path / "records.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sheet1", index=False)
        pd.DataFrame([{"Part No": "A-1", "Alloy": "Ti-6Al-4V"}]).to_excel(
            writer, sheet_name="Alt", index=False
        )
    return path.read_bytes()


@pytest.fixture
def csv_bytes(sample_rows: list[dict]) -> bytes:
    df = pd.DataFrame(sample_rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


@pytest.fixture
def loaded_dataset(xlsx_bytes: bytes):
    return load_dataset(
        xlsx_bytes,
        filename="records.xlsx",
        sheet_name="Sheet1",
        part_number_column="Part Number",
    )


@pytest.fixture
def sample_record(loaded_dataset) -> PartRecord:
    from cnc_intelligence.part_lookup import lookup_part

    result = lookup_part(loaded_dataset, "2280")
    assert result.status == "found"
    return result.matches[0]


@pytest.fixture
def settings_ready() -> Settings:
    return Settings(
        OPENROUTER_API_KEY="sk-test-key-12345678",
        OPENROUTER_MODEL="test/model-id",
        REQUEST_TIMEOUT_SECONDS=5,
        MAX_OUTPUT_TOKENS=200,
        MAX_RETRIES=1,
    )


@pytest.fixture
def settings_missing_key() -> Settings:
    return Settings(
        OPENROUTER_API_KEY="",
        OPENROUTER_MODEL="test/model-id",
    )
