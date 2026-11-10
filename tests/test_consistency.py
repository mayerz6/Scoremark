import pandas as pd

from rules.consistency import apply_consistency_fixes


def test_name_column_is_title_cased():
    df = pd.DataFrame({"full_name": ["larry mayers", "JANE DOE"]})
    fixed, stats, changed = apply_consistency_fixes(df, {"full_name": "name"})

    assert list(fixed["full_name"]) == ["Larry Mayers", "Jane Doe"]
    assert stats[0]["rule"] == "title_case"
    assert stats[0]["autocorrected_count"] == 2
    assert changed.tolist() == [True, True]


def test_already_title_cased_name_is_not_counted_as_changed():
    df = pd.DataFrame({"full_name": ["Larry Mayers"]})
    fixed, stats, changed = apply_consistency_fixes(df, {"full_name": "name"})

    assert stats[0]["autocorrected_count"] == 0
    assert changed.tolist() == [False]


def test_email_column_is_lowercased():
    df = pd.DataFrame({"email": ["Larry@Example.COM"]})
    fixed, stats, changed = apply_consistency_fixes(df, {"email": "email"})

    assert fixed["email"].iloc[0] == "larry@example.com"
    assert changed.iloc[0] is True or changed.iloc[0] == True  # noqa: E712


def test_date_column_is_reformatted_to_canonical_format():
    df = pd.DataFrame({"signup_date": ["2024-03-05"]})
    fixed, stats, changed = apply_consistency_fixes(df, {"signup_date": "date"})

    assert fixed["signup_date"].iloc[0] == "03/05/2024"
    assert stats[0]["rule"] == "canonical_date_format"


def test_day_first_column_is_converted_consistently_including_ambiguous_days():
    # "25/03" proves the column is day-first, so "05/03" is 5 March too --
    # not 3 May, which is what per-value parsing used to produce.
    df = pd.DataFrame({"signup_date": ["25/03/2024", "05/03/2024", "2024-03-07"]})
    fixed, _, _ = apply_consistency_fixes(df, {"signup_date": "date"})

    assert list(fixed["signup_date"]) == ["03/25/2024", "03/05/2024", "03/07/2024"]


def test_ambiguous_dates_are_untouched_when_the_column_gives_no_evidence():
    df = pd.DataFrame({"signup_date": ["5/3/2024", "04/02/2024"]})
    fixed, stats, changed = apply_consistency_fixes(df, {"signup_date": "date"})

    assert list(fixed["signup_date"]) == ["5/3/2024", "04/02/2024"]
    assert stats[0]["autocorrected_count"] == 0
    assert changed.tolist() == [False, False]


def test_unparseable_date_is_left_untouched_and_not_counted_as_changed():
    df = pd.DataFrame({"signup_date": ["not-a-date"]})
    fixed, stats, changed = apply_consistency_fixes(df, {"signup_date": "date"})

    assert fixed["signup_date"].iloc[0] == "not-a-date"
    assert changed.iloc[0] == False  # noqa: E712


def test_row_was_changed_reflects_any_fixed_column_in_that_row():
    df = pd.DataFrame({
        "full_name": ["larry mayers", "Jane Doe"],
        "email": ["LARRY@X.COM", "jane@x.com"],
    })
    _, _, changed = apply_consistency_fixes(df, {"full_name": "name", "email": "email"})

    # Row 0: both columns change. Row 1: neither does.
    assert changed.tolist() == [True, False]


def test_columns_not_typed_name_email_or_date_are_left_alone():
    df = pd.DataFrame({"notes": ["Some Free Text"]})
    fixed, stats, changed = apply_consistency_fixes(df, {"notes": "text"})

    assert fixed["notes"].iloc[0] == "Some Free Text"
    assert stats == []
    assert changed.tolist() == [False]
