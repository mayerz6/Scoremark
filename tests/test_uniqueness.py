import pandas as pd

from rules.uniqueness import infer_key_columns, score_uniqueness


def test_no_duplicates_when_every_key_value_is_distinct():
    df = pd.DataFrame({"email": ["a@x.com", "b@x.com", "c@x.com"]})
    result = score_uniqueness(df, key_columns=["email"])
    assert result["duplicate_row_count"] == 0
    assert result["duplicate_group_count"] == 0


def test_keeps_first_occurrence_and_flags_the_rest():
    df = pd.DataFrame({"email": ["a@x.com", "b@x.com", "a@x.com", "a@x.com"]})
    result = score_uniqueness(df, key_columns=["email"])

    # Row 0 is the first "a@x.com" -- it must never appear as a duplicate.
    duplicate_indices = [dup for dup, _first in result["duplicate_row_indices"]]
    assert 0 not in duplicate_indices
    assert set(duplicate_indices) == {2, 3}
    assert result["duplicate_group_count"] == 1
    assert result["duplicate_row_count"] == 2


def test_composite_key_across_multiple_columns():
    df = pd.DataFrame({
        "first": ["Larry", "Larry", "Jane"],
        "last": ["Mayers", "Mayers", "Doe"],
    })
    result = score_uniqueness(df, key_columns=["first", "last"])
    assert result["duplicate_row_count"] == 1


def test_infer_key_columns_picks_the_most_unique_candidate_column():
    df = pd.DataFrame({
        "email": [f"user{i}@x.com" for i in range(25)],
        "zip_code": ["02134"] * 25,  # not unique at all, must lose
    })
    column_types = {"email": "email", "zip_code": "integer_code"}
    key_columns, source = infer_key_columns(df, column_types)
    assert key_columns == ["email"]
    assert source == "inferred"


def test_infer_key_columns_falls_back_to_full_row_when_nothing_qualifies():
    df = pd.DataFrame({"zip_code": ["02134"] * 25})
    column_types = {"zip_code": "integer_code"}
    key_columns, source = infer_key_columns(df, column_types)
    assert source == "fallback_full_row"
    assert key_columns == list(df.columns)


def test_rows_with_all_key_values_missing_are_never_duplicates():
    df = pd.DataFrame({"email": ["a@x.com", "", "", "N/A", "  "]})
    result = score_uniqueness(df, key_columns=["email"])
    assert result["duplicate_row_count"] == 0


def test_key_comparison_ignores_case_and_surrounding_spaces():
    df = pd.DataFrame({"email": ["Kamal@X.com", " kamal@x.com "]})
    result = score_uniqueness(df, key_columns=["email"])
    assert result["duplicate_row_indices"] == [(1, 0)]
