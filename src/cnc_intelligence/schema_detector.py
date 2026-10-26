"""Inspect columns and help identify the part-number field."""

from __future__ import annotations

import re
from collections.abc import Iterable

# Conservative normalized name patterns for part-number columns.
# Ordered from most specific to least specific.
_PART_NUMBER_PATTERNS: list[tuple[str, int]] = [
    (r"^part[_\s\-]?number$", 100),
    (r"^part[_\s\-]?no\.?$", 95),
    (r"^part[_\s\-]?num$", 90),
    (r"^part[_\s\-]?#$", 90),
    (r"^part[_\s\-]?id$", 85),
    (r"^pn$", 80),
    (r"^p/?n$", 80),
    (r"^item[_\s\-]?number$", 70),
    (r"^item[_\s\-]?no\.?$", 65),
    (r"^component[_\s\-]?number$", 60),
    (r"^part$", 50),
]


def normalize_column_name(name: str) -> str:
    """Normalize a column name for matching without destroying the original."""
    text = str(name).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def score_part_number_column(column_name: str) -> int:
    """Return a confidence score (0–100) for how likely a column is a part number."""
    normalized = normalize_column_name(column_name)
    # Also try underscore-normalized form
    underscored = normalized.replace(" ", "_").replace("-", "_")
    best = 0
    for pattern, score in _PART_NUMBER_PATTERNS:
        if re.match(pattern, normalized) or re.match(pattern, underscored):
            best = max(best, score)
    return best


def suggest_part_number_columns(columns: Iterable[str]) -> list[str]:
    """
    Return candidate part-number columns sorted by confidence (highest first).

    Only includes columns that score above zero. Does not auto-select when
    multiple strong candidates exist — the caller must ask the user.
    """
    scored: list[tuple[int, str]] = []
    for col in columns:
        score = score_part_number_column(col)
        if score > 0:
            scored.append((score, col))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [col for _, col in scored]


def auto_select_part_number_column(columns: Iterable[str]) -> str | None:
    """
    Auto-select a part-number column only when there is a single clear winner.

    Returns None if there are zero candidates or multiple candidates with
    equal top scores (ambiguous).
    """
    candidates = suggest_part_number_columns(columns)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Multiple candidates: only auto-select if the top score is uniquely highest
    # and clearly strong (>= 85).
    top_score = score_part_number_column(candidates[0])
    second_score = score_part_number_column(candidates[1])
    if top_score >= 85 and top_score > second_score:
        return candidates[0]
    return None


def build_column_map(original_columns: list[str]) -> dict[str, str]:
    """
    Map normalized names to original column names.

    If two columns normalize to the same key, the first wins and later
    duplicates are tracked separately by the data loader.
    """
    mapping: dict[str, str] = {}
    for col in original_columns:
        key = normalize_column_name(col)
        if key not in mapping:
            mapping[key] = col
    return mapping
