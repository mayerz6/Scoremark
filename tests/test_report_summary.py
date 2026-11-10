"""
Unit tests for report_summary.py, plus one end-to-end cross-check against
the real messy sample's actual report -- same ground-truth discipline as
tests/test_analyze_pipeline.py, applied one layer up (the numbers a stat
card shows, not just the numbers the rules engine computes).
"""

import json
from pathlib import Path

from report_summary import build_chart_data, build_summary
from rules.disposition import run_pipeline
from rules.io import read_csv_as_text

GROUND_TRUTH = json.loads(Path("samples/injected_counts.json").read_text())


def _tiny_report():
    return {
        "completeness": [
            {"column": "a", "missing_count": 1, "total_rows": 4, "missing_pct": 25.0},
            {"column": "b", "missing_count": 0, "total_rows": 4, "missing_pct": 0.0},
        ],
        "validity": [
            {"column": "a", "type": "text", "confidence": 1.0, "invalid_count": None, "note": "unscored"},
            {"column": "b", "type": "email", "confidence": 1.0, "invalid_count": 1, "invalid_pct": 25.0, "examples": []},
        ],
        "uniqueness": {"key_columns": ["b"], "key_source": "declared", "duplicate_group_count": 1, "duplicate_row_count": 1},
        "consistency": [
            {"column": "b", "rule": "lowercase", "autocorrected_count": 2, "autocorrected_pct": 50.0},
        ],
    }


def test_build_summary_computes_one_headline_number_per_rule():
    summary = build_summary(_tiny_report(), total_rows=4)

    assert summary["total_missing"] == 1
    assert summary["completeness_pct"] == round(100 - (1 / (4 * 2) * 100), 2)
    assert summary["total_invalid"] == 1
    assert summary["scored_columns"] == 1
    assert summary["unscored_columns"] == 1
    assert summary["duplicate_count"] == 1
    assert summary["duplicate_pct"] == 25.0
    assert summary["total_autocorrected"] == 2


def test_build_summary_handles_a_report_with_zero_rows_without_dividing_by_zero():
    empty_report = {
        "completeness": [],
        "validity": [],
        "uniqueness": {"key_columns": [], "key_source": "declared", "duplicate_group_count": 0, "duplicate_row_count": 0},
        "consistency": [],
    }
    summary = build_summary(empty_report, total_rows=0)
    assert summary["completeness_pct"] == 100.0
    assert summary["duplicate_pct"] == 0.0


def test_build_chart_data_aligns_missing_and_invalid_percentages_by_column():
    chart_data = build_chart_data(_tiny_report())

    assert chart_data["columns"] == ["a", "b"]
    assert chart_data["missing_pct"] == [25.0, 0.0]
    # column "a" is unscored (no invalid_pct key at all) -- must default to 0, not crash
    assert chart_data["invalid_pct"] == [0, 25.0]


def test_against_the_real_messy_sample_report_matches_injected_ground_truth():
    dataframe = read_csv_as_text("samples/messy_sample.csv")
    schema = {
        "customer_id": "text", "full_name": "name", "email": "email",
        "phone": "phone", "signup_date": "date", "zip_code": "integer_code",
    }
    result = run_pipeline(dataframe, declared_schema=schema, key_columns=["email"])

    summary = build_summary(result["report"], total_rows=len(dataframe))

    assert summary["total_missing"] == GROUND_TRUTH["missing_phone_rows"]
    assert summary["total_invalid"] == GROUND_TRUTH["invalid_email_rows"]
    assert summary["duplicate_count"] == GROUND_TRUTH["duplicated_rows"]
    assert summary["total_autocorrected"] == GROUND_TRUTH["inconsistent_name_rows"]

    chart_data = build_chart_data(result["report"])
    phone_index = chart_data["columns"].index("phone")
    email_index = chart_data["columns"].index("email")
    assert chart_data["missing_pct"][phone_index] == round(
        GROUND_TRUTH["missing_phone_rows"] / GROUND_TRUTH["messy_sample_row_count"] * 100, 2
    )
    assert chart_data["invalid_pct"][email_index] == round(
        GROUND_TRUTH["invalid_email_rows"] / GROUND_TRUTH["messy_sample_row_count"] * 100, 2
    )
