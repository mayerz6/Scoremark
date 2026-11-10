"""
Ties the four rules together into the full pipeline from
scoremark_project.md's "Row Disposition" section:

    split a combined name column (name_split.py) -> resolve schema ->
    apply safe Consistency fixes -> score everything on
    the fixed data -> route every row to clean.csv or garbage.csv

This is the one place all four rule modules are used together, and it's
deliberately built to reuse the exact same per-cell primitives
(schema.missing_kind, schema.is_invalid_value) that completeness.py and
validity.py use for their aggregate stats -- so the report's numbers and
the garbage file's row count can never silently drift apart from each other.

What sends a row to garbage.csv:
  - empty record:   every cell is empty -- the line is only delimiters
  - malformed row:  more fields than the header (see io.read_csv_rows)
  - invalid value:  a present value that fails its column's type check
  - duplicate:      repeats an earlier row's key

What does NOT: a missing value. Every field is optional; missing values
are measured (Completeness, occupancy) but never rejected.
"""

from __future__ import annotations

import pandas as pd

from .completeness import score_completeness
from .consistency import apply_consistency_fixes
from .name_split import split_full_name_column
from .schema import infer_column_type, is_invalid_value, missing_kind
from .uniqueness import infer_key_columns, score_uniqueness
from .validity import score_validity


def resolve_column_types(df: pd.DataFrame, declared_schema: dict[str, str] | None) -> dict[str, str]:
    declared_schema = declared_schema or {}
    types = {}
    for column in df.columns:
        if column in declared_schema:
            types[column] = declared_schema[column]
        else:
            types[column] = infer_column_type(df[column].tolist(), header_name=column)["type"]
    return types


#: How many malformed rows the report itemizes; all of them are always in
#: the garbage file regardless.
_MAX_MALFORMED_LISTED = 20


def run_pipeline(
    df: pd.DataFrame,
    declared_schema: dict[str, str] | None = None,
    key_columns: list[str] | None = None,
    malformed_rows: list | None = None,
) -> dict:
    """
    malformed_rows: io.MalformedRow records set aside by io.read_csv_rows()
    -- rows that couldn't be split into the header's columns. They're never
    scored (no rule can judge a value that isn't in a known column), but
    every one of them lands in the garbage file with its line number and
    raw text, and the report counts them under "structure".

    Returns:
      {
        "report": {"structure": {...}, "completeness": [...], "validity": [...],
                   "uniqueness": {...}, "consistency": [...]},
        "clean_df": DataFrame,   # fixed rows that passed every check, + was_autocorrected
        "garbage_df": DataFrame, # failed rows, + original_row_number + failure_reasons
                                 #   (+ raw_row, only when malformed rows exist)
      }
    """
    malformed_rows = malformed_rows or []

    # Empty records (only delimiters, no text) aren't records at all: set
    # aside before anything is scored, so they can't skew type inference,
    # completeness/occupancy, or look like duplicates of each other.
    is_empty_record = pd.Series(
        [all(missing_kind(v) == "empty" for v in row) for row in df.itertuples(index=False, name=None)],
        index=df.index,
        dtype=bool,
    )
    empty_indices = list(df.index[is_empty_record])
    df = df[~is_empty_record]

    # Structural transformation, before typing: a combined "name" column
    # becomes firstname + lastname (see name_split.py), so every check and
    # both output files see the split columns.
    df, declared_schema, name_split_report = split_full_name_column(df, declared_schema)
    if name_split_report and key_columns and name_split_report["source_column"] in key_columns:
        i = key_columns.index(name_split_report["source_column"])
        key_columns = key_columns[:i] + name_split_report["into"] + key_columns[i + 1:]

    column_types = resolve_column_types(df, declared_schema)

    fixed_df, consistency_stats, row_was_changed = apply_consistency_fixes(df, column_types)

    completeness_stats = score_completeness(fixed_df)
    validity_stats = score_validity(fixed_df, declared_schema=declared_schema)

    if key_columns is not None:
        uniqueness_result = score_uniqueness(fixed_df, key_columns, key_source="declared")
    else:
        inferred_keys, key_source = infer_key_columns(fixed_df, column_types)
        uniqueness_result = score_uniqueness(fixed_df, inferred_keys, key_source=key_source)

    duplicate_of = dict(uniqueness_result["duplicate_row_indices"])  # {dup_index: first_seen_index}

    clean_records = []
    garbage_records = []

    for index, row in fixed_df.iterrows():
        reasons = []

        for column in fixed_df.columns:
            # Missing values are allowed -- is_invalid_value() never flags one.
            if is_invalid_value(row[column], column_types[column]):
                reasons.append(f"invalid:{column}")

        if index in duplicate_of:
            reasons.append(f"duplicate_of_row:{duplicate_of[index]}")

        if reasons:
            record = row.to_dict()
            record["original_row_number"] = index
            record["failure_reasons"] = "; ".join(reasons)
            garbage_records.append(record)
        else:
            record = row.to_dict()
            record["was_autocorrected"] = bool(row_was_changed.loc[index])
            clean_records.append(record)

    for index in empty_indices:
        record = {column: "" for column in fixed_df.columns}
        record["original_row_number"] = index
        record["failure_reasons"] = "empty_record"
        garbage_records.append(record)

    for bad in malformed_rows:
        record = {column: "" for column in fixed_df.columns}
        record["original_row_number"] = bad.row_number
        record["failure_reasons"] = (
            f"malformed_row:line {bad.line_number} has {bad.found_fields} fields, "
            f"expected {bad.expected_fields}"
        )
        record["raw_row"] = bad.raw
        garbage_records.append(record)

    # Header always present, even when a file is 100% clean or 100% flagged
    # -- a header-only CSV is still a valid, self-describing download.
    clean_columns = list(fixed_df.columns) + ["was_autocorrected"]
    garbage_columns = list(fixed_df.columns) + ["original_row_number", "failure_reasons"]
    if malformed_rows:
        garbage_columns.append("raw_row")

    clean_df = pd.DataFrame(clean_records, columns=clean_columns)
    garbage_df = pd.DataFrame(garbage_records, columns=garbage_columns)
    if len(garbage_df):
        garbage_df = garbage_df.sort_values("original_row_number", kind="stable").reset_index(drop=True)

    return {
        "report": {
            "structure": {
                "scored_row_count": len(fixed_df),
                # Rows, not cells: one name split over two columns is one fix.
                "autocorrected_row_count": int(row_was_changed.sum()),
                "empty_record_count": len(empty_indices),
                "malformed_row_count": len(malformed_rows),
                "malformed_rows": [
                    {"line_number": m.line_number, "found_fields": m.found_fields, "expected_fields": m.expected_fields}
                    for m in malformed_rows[:_MAX_MALFORMED_LISTED]
                ],
            },
            "transformations": {"name_split": name_split_report},
            "completeness": completeness_stats,
            "validity": validity_stats,
            "uniqueness": {k: v for k, v in uniqueness_result.items() if k != "duplicate_row_indices"},
            "consistency": consistency_stats,
        },
        "clean_df": clean_df,
        "garbage_df": garbage_df,
        "column_types": column_types,
    }
