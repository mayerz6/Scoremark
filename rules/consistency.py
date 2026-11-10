"""
Consistency: the only rule that changes data, and only in ways that are
provably safe -- see scoremark_project.md's "Row Disposition" section for
why these three specific fixes (and no others) are considered safe:

  - name columns   -> Title Case
  - email columns  -> lowercase
  - date columns   -> canonical MM/DD/YYYY, only when the original value
                       parses cleanly under a known format AND its
                       day/month order is certain -- either from the value
                       itself (year-first, or a day above 12) or from the
                       rest of its column (see schema.detect_day_month_order).
                       An ambiguous "05/03/2024" in a column with no
                       evidence either way is left untouched.

Nothing here invents a value. A date that doesn't parse is left exactly as
it was (and will fail Validity instead, where that belongs).
"""

from __future__ import annotations

import pandas as pd

from .schema import canonicalize_date, detect_day_month_order, is_missing

_RULE_NAME_BY_TYPE = {
    "name": "title_case",
    "email": "lowercase",
    "date": "canonical_date_format",
}


def _fix_value(value, column_type: str, day_month_order: str | None = None):
    if is_missing(value):
        return value
    if column_type == "name":
        return str(value).strip().title()
    if column_type == "email":
        return str(value).strip().lower()
    if column_type == "date":
        return canonicalize_date(value, day_month_order)
    return value


def apply_consistency_fixes(
    df: pd.DataFrame,
    column_types: dict[str, str],
) -> tuple[pd.DataFrame, list[dict], pd.Series]:
    """
    column_types: {column: type}, from either the declared schema or
    schema.infer_column_type(), for every column worth fixing (columns not
    typed "name"/"email"/"date" are left untouched).

    Returns (fixed_df, stats, row_was_changed):
      - fixed_df: a copy of df with the safe fixes applied.
      - stats: one dict per fixed column, matching scoremark_project.md's
        Consistency output contract.
      - row_was_changed: a boolean Series, indexed like df, True for any
        row where at least one fix actually changed a value -- this is what
        disposition.py uses to set the clean file's `was_autocorrected` column.
    """
    fixed = df.copy()
    stats = []
    row_was_changed = pd.Series(False, index=df.index)

    for column, column_type in column_types.items():
        if column_type not in _RULE_NAME_BY_TYPE:
            continue

        original = df[column]
        # Decided once per column, never per value -- deciding per value is
        # what turned a day-first column into a mix of right and wrong dates.
        order = detect_day_month_order(original.tolist()) if column_type == "date" else None
        updated = original.apply(lambda v: _fix_value(v, column_type, order))
        changed_mask = updated.ne(original)

        row_was_changed = row_was_changed | changed_mask
        fixed[column] = updated

        changed_count = int(changed_mask.sum())
        total = len(df)
        stats.append({
            "column": column,
            "rule": _RULE_NAME_BY_TYPE[column_type],
            "autocorrected_count": changed_count,
            "autocorrected_pct": round((changed_count / total) * 100, 2) if total else 0.0,
        })

    return fixed, stats, row_was_changed
