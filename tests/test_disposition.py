import pandas as pd
import pytest

from rules.disposition import run_pipeline

SCHEMA = {
    "customer_id": "integer_code",
    "full_name": "name",
    "email": "email",
    "signup_date": "date",
}


def _make_df(rows):
    return pd.DataFrame(rows, columns=["customer_id", "full_name", "email", "signup_date"])


def test_inferred_iso_date_column_is_never_used_as_the_duplicate_key():
    # Regression: ISO dates were inferred as "phone" (a key candidate), so
    # two customers who signed up on the same day were flagged duplicates.
    df = pd.DataFrame({
        "notes": [f"customer note {i}" for i in range(25)],
        "signup": [f"2024-01-{(i % 24) + 1:02d}" for i in range(25)],  # one repeated day
    })
    result = run_pipeline(df)

    assert result["column_types"]["signup"] == "date"
    assert result["report"]["uniqueness"]["key_columns"] != ["signup"]
    assert result["report"]["uniqueness"]["duplicate_row_count"] == 0


def test_a_perfectly_clean_row_ends_up_in_clean_with_no_autocorrection():
    df = _make_df([["001", "Larry Mayers", "larry@x.com", "01/15/2024"]])
    result = run_pipeline(df, declared_schema=SCHEMA, key_columns=["email"])

    assert len(result["clean_df"]) == 1
    assert len(result["garbage_df"]) == 0
    assert result["clean_df"].iloc[0]["was_autocorrected"] == False  # noqa: E712


def test_a_row_needing_only_formatting_fixes_still_ends_up_in_clean():
    # Lowercased name, differently-formatted-but-valid date -- both are
    # safe Consistency fixes, neither is a quality failure.
    df = _make_df([["001", "larry mayers", "larry@x.com", "2024-01-15"]])
    result = run_pipeline(df, declared_schema=SCHEMA, key_columns=["email"])

    assert len(result["clean_df"]) == 1
    assert len(result["garbage_df"]) == 0
    clean_row = result["clean_df"].iloc[0]
    assert (clean_row["firstname"], clean_row["lastname"]) == ("Larry", "Mayers")
    assert clean_row["signup_date"] == "01/15/2024"
    assert clean_row["was_autocorrected"] == True  # noqa: E712


@pytest.mark.parametrize("missing", ["", "   ", "NULL", "N/A"])
def test_a_row_with_a_missing_value_stays_clean_because_fields_are_optional(missing):
    df = _make_df([["001", "Larry Mayers", missing, "01/15/2024"]])
    result = run_pipeline(df, declared_schema=SCHEMA, key_columns=["email"])

    assert len(result["clean_df"]) == 1
    assert len(result["garbage_df"]) == 0
    email = next(c for c in result["report"]["completeness"] if c["column"] == "email")
    assert email["missing_count"] == 1  # still measured


@pytest.mark.parametrize("empty_row", [["", "", "", ""], ["  ", "", " ", ""]])
def test_an_empty_record_goes_to_garbage_and_is_not_scored(empty_row):
    df = _make_df([["001", "Larry Mayers", "larry@x.com", "01/15/2024"], empty_row])
    result = run_pipeline(df, declared_schema=SCHEMA, key_columns=["email"])

    assert len(result["clean_df"]) == 1
    [garbage] = result["garbage_df"].to_dict("records")
    assert (garbage["original_row_number"], garbage["failure_reasons"]) == (1, "empty_record")
    assert result["report"]["structure"]["empty_record_count"] == 1
    assert result["report"]["structure"]["scored_row_count"] == 1
    # Not counted as 4 missing cells -- it isn't a record at all.
    assert all(c["missing_count"] == 0 and c["total_rows"] == 1 for c in result["report"]["completeness"])


def test_a_row_of_null_placeholders_is_not_an_empty_record():
    # "NULL" is text in the file; only a line of bare delimiters is empty.
    df = _make_df([["NULL", "NULL", "NULL", "NULL"]])
    result = run_pipeline(df, declared_schema=SCHEMA, key_columns=["email"])
    assert result["report"]["structure"]["empty_record_count"] == 0
    assert len(result["clean_df"]) == 1


def test_a_row_with_an_invalid_value_goes_to_garbage_with_a_reason():
    df = _make_df([["001", "Larry Mayers", "not-an-email", "01/15/2024"]])
    result = run_pipeline(df, declared_schema=SCHEMA, key_columns=["email"])

    assert len(result["garbage_df"]) == 1
    assert "invalid:email" in result["garbage_df"].iloc[0]["failure_reasons"]


def test_duplicate_rows_keep_the_first_occurrence_in_clean_and_send_the_rest_to_garbage():
    df = _make_df([
        ["001", "Larry Mayers", "larry@x.com", "01/15/2024"],
        ["002", "Jane Doe", "jane@x.com", "02/01/2024"],
        ["003", "Larry Mayers Snr", "larry@x.com", "01/15/2024"],  # same email, duplicate
    ])
    result = run_pipeline(df, declared_schema=SCHEMA, key_columns=["email"])

    assert len(result["clean_df"]) == 2
    assert len(result["garbage_df"]) == 1
    garbage_row = result["garbage_df"].iloc[0]
    assert garbage_row["original_row_number"] == 2
    assert "duplicate_of_row:0" in garbage_row["failure_reasons"]


def test_a_row_can_fail_more_than_one_rule_at_once():
    df = _make_df([
        ["001", "Larry Mayers", "larry@x.com", "01/15/2024"],
        ["002", "Jane Doe", "jane@x.com", "13/45/2024"],  # invalid date
        ["003", "Larry Mayers Snr", "larry@x.com", "99/99/9999"],  # invalid date AND duplicate of row 0
    ])
    result = run_pipeline(df, declared_schema=SCHEMA, key_columns=["email"])

    assert len(result["garbage_df"]) == 2
    reasons_by_row = dict(zip(
        result["garbage_df"]["original_row_number"],
        result["garbage_df"]["failure_reasons"],
    ))
    assert reasons_by_row[1] == "invalid:signup_date"
    assert reasons_by_row[2] == "invalid:signup_date; duplicate_of_row:0"


def test_report_counts_agree_with_the_actual_garbage_row_count():
    # This is the property the whole sample-data proof in Phase 3 depends
    # on: the aggregate report and the per-row routing must never disagree.
    df = _make_df([
        ["001", "Larry Mayers", "larry@x.com", "01/15/2024"],
        ["002", "Jane Doe", "", "02/01/2024"],
        ["003", "Bob Smith", "not-an-email", "03/01/2024"],
    ])
    result = run_pipeline(df, declared_schema=SCHEMA, key_columns=["email"])

    email_report = next(c for c in result["report"]["completeness"] if c["column"] == "email")
    assert email_report["missing_count"] == 1

    email_validity = next(c for c in result["report"]["validity"] if c["column"] == "email")
    # "not-an-email" counts as invalid; the empty cell does not (it's
    # Completeness's count, not Validity's -- and missing is allowed).
    assert email_validity["invalid_count"] == 1

    assert len(result["garbage_df"]) == email_validity["invalid_count"]


def test_malformed_rows_land_in_garbage_with_line_number_and_raw_text():
    import io
    from rules.io import read_csv_rows

    content = "customer_id,full_name,email,signup_date\n001,Larry Mayers,l@x.com,01/15/2024\n002,Alamo, Kamal,k@x.com,01/16/2024\n"
    read = read_csv_rows(io.StringIO(content))
    result = run_pipeline(read.dataframe, declared_schema=SCHEMA, key_columns=["email"],
                          malformed_rows=read.malformed_rows)

    assert len(result["clean_df"]) == 1
    [bad] = result["garbage_df"].to_dict("records")
    assert bad["original_row_number"] == 1
    assert bad["failure_reasons"] == "malformed_row:line 3 has 5 fields, expected 4"
    assert bad["raw_row"] == "002,Alamo, Kamal,k@x.com,01/16/2024"
    assert result["report"]["structure"]["malformed_row_count"] == 1


def test_downloads_keep_their_header_even_when_empty():
    df = _make_df([["001", "Larry Mayers", "larry@x.com", "01/15/2024"]])
    result = run_pipeline(df, declared_schema=SCHEMA, key_columns=["email"])
    split_columns = ["customer_id", "firstname", "lastname", "email", "signup_date"]
    assert list(result["clean_df"].columns) == split_columns + ["was_autocorrected"]
    assert list(result["garbage_df"].columns) == split_columns + ["original_row_number", "failure_reasons"]
    assert len(result["garbage_df"]) == 0
