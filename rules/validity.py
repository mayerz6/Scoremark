"""
Validity: type/format conformance per column, against a declared or
inferred type (see schema.py for how the type is decided).

A value counts as invalid only if it's present and fails the column's
type checker.

A missing value -- empty, or a null placeholder like "NULL" / "N/A" -- is
NOT invalid: fields are optional, and missing values are Completeness's
(and occupancy's) concern alone.
"name"-typed columns are never scored for validity at all: there's no
trustworthy value-pattern check for "is this a real human name" (see
schema.infer_column_type's docstring), so Validity stays silent on them
rather than pretending to check something it can't.
"""

from __future__ import annotations

import pandas as pd

from .schema import (
    CHECKER_BY_TYPE,
    infer_column_type,
    is_invalid_value,
    missing_kind,
)

#: Types that Validity never scores -- see module docstring.
_UNSCORED_TYPES = {"text", "name", "unclassified", "insufficient_data"}

_MAX_EXAMPLES = 5


def score_validity(df: pd.DataFrame, declared_schema: dict[str, str] | None = None) -> list[dict]:
    """
    declared_schema: optional {column: type} for canned samples, where the
    type is already known instead of inferred. Types must be keys that also
    appear in schema.CHECKER_BY_TYPE (or "name"/"text", which are skipped).

    Returns one result dict per column:
      {"column", "type", "confidence", "invalid_count", "invalid_pct", "examples"}
    or, for unscored/low-confidence columns:
      {"column", "type", "confidence", "invalid_count": None, "note": str}
    """
    declared_schema = declared_schema or {}
    results = []

    for column in df.columns:
        values = df[column].tolist()

        if column in declared_schema:
            column_type = declared_schema[column]
            confidence = 1.0
        else:
            inferred = infer_column_type(values, header_name=column)
            column_type = inferred["type"]
            confidence = inferred["confidence"]

        if column_type in _UNSCORED_TYPES or column_type not in CHECKER_BY_TYPE:
            results.append({
                "column": column,
                "type": column_type,
                "confidence": confidence,
                "invalid_count": None,
                "note": _unscored_reason(column_type),
            })
            continue

        checker = CHECKER_BY_TYPE[column_type]
        invalid_examples = []
        invalid_count = 0

        for value in values:
            if is_invalid_value(value, column_type):
                invalid_count += 1
                if len(invalid_examples) < _MAX_EXAMPLES:
                    invalid_examples.append(value)

        total = len(values)
        results.append({
            "column": column,
            "type": column_type,
            "confidence": confidence,
            "invalid_count": invalid_count,
            "invalid_pct": round((invalid_count / total) * 100, 2) if total else 0.0,
            "examples": invalid_examples,
        })

    return results


def _unscored_reason(column_type: str) -> str:
    if column_type == "name":
        return "Name columns are not format-checked; see Consistency for formatting instead."
    if column_type == "insufficient_data":
        return "Fewer than the minimum sample size of non-empty values; validity not scored."
    if column_type == "unclassified":
        return "No candidate type reached the confidence threshold; validity not scored."
    return "This column's type is not validity-checked."
