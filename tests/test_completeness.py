import pandas as pd

from rules.completeness import score_completeness


def test_fully_populated_column_has_zero_missing():
    df = pd.DataFrame({"email": ["a@x.com", "b@x.com", "c@x.com"]})
    result = score_completeness(df)
    assert result == [{
        "column": "email", "missing_count": 0, "total_rows": 3, "missing_pct": 0.0,
    }]


def test_counts_truly_empty_cells():
    df = pd.DataFrame({"phone": ["555-1234", "", "  "]})
    result = score_completeness(df)[0]
    assert result["missing_count"] == 2
    assert result["missing_pct"] == round(2 / 3 * 100, 2)


def test_counts_null_sentinel_strings_as_missing_too():
    df = pd.DataFrame({"zip": ["02134", "NULL", "N/A"]})
    result = score_completeness(df)[0]
    assert result["missing_count"] == 2


def test_scores_every_column_independently():
    df = pd.DataFrame({
        "complete_col": ["a", "b", "c"],
        "half_empty_col": ["a", "", "c"],
    })
    results = {r["column"]: r for r in score_completeness(df)}
    assert results["complete_col"]["missing_count"] == 0
    assert results["half_empty_col"]["missing_count"] == 1
