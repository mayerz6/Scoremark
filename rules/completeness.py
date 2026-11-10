"""
Completeness: the missing-value rate per column.

A value is "missing" if it's truly empty, or if it's a recognized
null-sentinel string ("NULL", "N/A", etc.) -- see schema.missing_kind().

Every field is optional: this is a measurement (how dense is each
column?), never a reason to reject a row. Its inverse is each column's
occupancy, which the results page charts.
"""

from __future__ import annotations

import pandas as pd

from .schema import is_missing


def score_completeness(df: pd.DataFrame) -> list[dict]:
    """
    Returns one result dict per column:
      {"column": str, "missing_count": int, "total_rows": int, "missing_pct": float}
    """
    results = []
    total_rows = len(df)

    for column in df.columns:
        missing_count = sum(1 for value in df[column] if is_missing(value))
        missing_pct = round((missing_count / total_rows) * 100, 2) if total_rows else 0.0

        results.append({
            "column": column,
            "missing_count": missing_count,
            "total_rows": total_rows,
            "missing_pct": missing_pct,
        })

    return results
