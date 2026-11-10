"""
SCORE-3: headline stat-card numbers and chart-ready arrays, derived from
a rules/disposition.py report. Computed here as plain, independently
testable functions -- not as logic buried inside results.html's Jinja
template, the same reasoning upload_guards.py and run_store.py were each
kept as their own small module instead of inline in app.py.
"""

from __future__ import annotations


def _scored_rows(report: dict, fallback: int) -> int:
    """Rows the rules actually scored: excludes empty records and malformed rows."""
    return report.get("structure", {}).get("scored_row_count", fallback)


def build_summary(report: dict, total_rows: int) -> dict:
    """
    One headline number per rule -- what the stat cards on the results
    page show at a glance, before anyone reads the detailed tables below
    them.

    Percentages are over the rows that were scored: an empty record or a
    malformed row isn't a record whose fields can be counted.
    """
    scored_rows = _scored_rows(report, total_rows)
    structure = report.get("structure", {})

    total_columns = len(report["completeness"])
    total_missing = sum(row["missing_count"] for row in report["completeness"])
    total_cells = scored_rows * total_columns
    completeness_pct = round(100 - (total_missing / total_cells * 100), 2) if total_cells else 100.0

    scored_validity = [row for row in report["validity"] if row["invalid_count"] is not None]
    total_invalid = sum(row["invalid_count"] for row in scored_validity)

    duplicate_count = report["uniqueness"]["duplicate_row_count"]
    duplicate_pct = round(duplicate_count / scored_rows * 100, 2) if scored_rows else 0.0

    # Rows, not cells -- after the name split, one fixed name is two cells.
    total_autocorrected = structure.get(
        "autocorrected_row_count",
        sum(row["autocorrected_count"] for row in report["consistency"]),
    )

    return {
        "malformed_count": structure.get("malformed_row_count", 0),
        "empty_record_count": structure.get("empty_record_count", 0),
        "scored_rows": scored_rows,
        "completeness_pct": completeness_pct,
        "total_missing": total_missing,
        "total_invalid": total_invalid,
        "scored_columns": len(scored_validity),
        "unscored_columns": total_columns - len(scored_validity),
        "duplicate_count": duplicate_count,
        "duplicate_pct": duplicate_pct,
        "total_autocorrected": total_autocorrected,
    }


def build_occupancy(report: dict) -> list[dict]:
    """
    Per-column occupancy -- the share of scored rows where the field holds
    a real value (not empty, not a null placeholder like "NULL"/"N/A") --
    sorted densest first. The inverse of Completeness's missing %, so the
    two can never disagree.
    """
    has_rows = _scored_rows(report, 0) > 0
    occupancy = [
        {
            "column": row["column"],
            "filled_count": row["total_rows"] - row["missing_count"],
            "occupancy_pct": round(100 - row["missing_pct"], 2) if has_rows else 0.0,
        }
        for row in report["completeness"]
    ]
    return sorted(occupancy, key=lambda row: row["occupancy_pct"], reverse=True)


def build_chart_data(report: dict) -> dict:
    """
    Per-column Missing% (from Completeness) and Invalid% (from Validity),
    aligned into parallel arrays Chart.js can consume directly. Uses
    Completeness's column list as the spine -- it's the one rule
    guaranteed to have exactly one row per column in the dataset, unlike
    Validity (unscored columns have no invalid_pct key at all) or
    Consistency (only columns that got a fix rule appear).

    Plus the occupancy chart's own arrays, sorted densest first.
    """
    validity_by_column = {row["column"]: row for row in report["validity"]}

    columns = []
    missing_pct = []
    invalid_pct = []

    for row in report["completeness"]:
        column = row["column"]
        columns.append(column)
        missing_pct.append(row["missing_pct"])
        invalid_pct.append(validity_by_column.get(column, {}).get("invalid_pct") or 0)

    occupancy = build_occupancy(report)

    return {
        "columns": columns,
        "missing_pct": missing_pct,
        "invalid_pct": invalid_pct,
        "occupancy_columns": [row["column"] for row in occupancy],
        "occupancy_pct": [row["occupancy_pct"] for row in occupancy],
    }
