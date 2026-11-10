"""
Uniqueness: duplicate rows, by a declared or inferred key.

Duplicate policy (confirmed in planning): the FIRST occurrence (in original
row order) of each key is kept; every later occurrence of the same key is a
duplicate. This module only scores and locates duplicates -- the actual
clean/garbage routing decision is made later by disposition.py, which reads
`duplicate_row_indices` from this result.
"""

from __future__ import annotations

import pandas as pd

from .schema import is_missing

#: A column is a plausible key if it's at least this unique among its own
#: non-missing values. Used by infer_key_columns() when no key is declared.
_KEY_UNIQUENESS_THRESHOLD = 0.95

#: Inferred types worth considering as a key at all -- a "text" column of
#: free-form notes is never a sensible key even if it happens to be unique.
_KEY_CANDIDATE_TYPES = {"email", "phone", "integer_code", "integer"}


def infer_key_columns(df: pd.DataFrame, column_types: dict[str, str]) -> tuple[list[str], str]:
    """
    Picks a key column from columns typed as email/phone/integer_code/integer
    (see schema.py) whose own non-missing values are almost all unique.
    Falls back to the whole row if nothing qualifies.

    Returns (key_columns, key_source) where key_source is "inferred" or
    "fallback_full_row".
    """
    best_column = None
    best_ratio = 0.0

    for column, column_type in column_types.items():
        if column_type not in _KEY_CANDIDATE_TYPES:
            continue

        values = [v for v in df[column].tolist() if not is_missing(v)]
        if not values:
            continue

        ratio = len(set(values)) / len(values)
        if ratio >= _KEY_UNIQUENESS_THRESHOLD and ratio > best_ratio:
            best_column = column
            best_ratio = ratio

    if best_column is not None:
        return [best_column], "inferred"

    return list(df.columns), "fallback_full_row"


def score_uniqueness(
    df: pd.DataFrame,
    key_columns: list[str],
    key_source: str = "declared",
) -> dict:
    """
    Returns:
      {
        "key_columns": [...], "key_source": str,
        "duplicate_group_count": int, "duplicate_row_count": int,
        "duplicate_row_indices": [(duplicate_index, first_seen_index), ...],
      }

    Keys are compared trimmed and case-insensitively ("A@X.com " == "a@x.com"),
    and a row whose key values are ALL missing is never a duplicate: blank
    means "unknown," not "the same" -- otherwise every row without an email
    was flagged as a duplicate of the first such row. Both rules match the
    batch ETL tool's DeduplicationEngine.
    """
    first_seen: dict[tuple, int] = {}
    duplicate_row_indices: list[tuple[int, int]] = []

    for index, row in df.iterrows():
        values = [row[column] for column in key_columns]
        if all(is_missing(v) for v in values):
            continue
        key = tuple("" if is_missing(v) else str(v).strip().lower() for v in values)
        if key in first_seen:
            duplicate_row_indices.append((index, first_seen[key]))
        else:
            first_seen[key] = index

    duplicate_group_count = len({first for _, first in duplicate_row_indices})

    return {
        "key_columns": key_columns,
        "key_source": key_source,
        "duplicate_group_count": duplicate_group_count,
        "duplicate_row_count": len(duplicate_row_indices),
        "duplicate_row_indices": duplicate_row_indices,
    }
