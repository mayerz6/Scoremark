import pandas as pd

from rules.validity import score_validity


def test_declared_email_column_with_no_bad_values():
    df = pd.DataFrame({"email": ["a@x.com", "b@x.com", "c@x.com"]})
    result = score_validity(df, declared_schema={"email": "email"})[0]
    assert result["type"] == "email"
    assert result["invalid_count"] == 0


def test_declared_email_column_flags_a_malformed_value():
    df = pd.DataFrame({"email": ["a@x.com", "not-an-email", "c@x.com"]})
    result = score_validity(df, declared_schema={"email": "email"})[0]
    assert result["invalid_count"] == 1
    assert "not-an-email" in result["examples"]


def test_null_placeholder_counts_as_missing_not_invalid():
    # "N/A" / "NULL" is how many exports write "no value" -- missing (and
    # allowed), not a malformed email.
    df = pd.DataFrame({"email": ["a@x.com", "N/A", "NULL", "c@x.com"]})
    result = score_validity(df, declared_schema={"email": "email"})[0]
    assert result["invalid_count"] == 0


def test_truly_empty_cell_is_not_counted_as_invalid():
    # Completeness's job, not Validity's -- see the module docstring.
    df = pd.DataFrame({"email": ["a@x.com", "", "c@x.com"]})
    result = score_validity(df, declared_schema={"email": "email"})[0]
    assert result["invalid_count"] == 0


def test_name_columns_are_never_validity_scored():
    df = pd.DataFrame({"full_name": ["Larry Mayers", "Jane Doe", "Bob Smith"]})
    result = score_validity(df, declared_schema={"full_name": "name"})[0]
    assert result["invalid_count"] is None
    assert "not format-checked" in result["note"]


def test_unclassified_column_is_reported_but_not_scored():
    values = ["note " + str(i) if i % 2 else "2024-01-01" for i in range(30)]
    df = pd.DataFrame({"mixed": values})
    result = score_validity(df)[0]
    assert result["type"] == "unclassified"
    assert result["invalid_count"] is None


def test_inferred_integer_code_column_flags_a_non_numeric_value():
    values = [f"{i:05d}" for i in range(24)] + ["not-a-code"]
    df = pd.DataFrame({"zip_code": values})
    result = score_validity(df)[0]
    assert result["type"] == "integer_code"
    assert result["invalid_count"] == 1
