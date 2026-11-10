import math

from rules.schema import (
    DAY_FIRST,
    MONTH_FIRST,
    canonicalize_date,
    detect_day_month_order,
    infer_column_type,
    missing_kind,
)


def test_missing_kind_treats_none_and_nan_as_empty():
    assert missing_kind(None) == "empty"
    assert missing_kind(float("nan")) == "empty"
    assert missing_kind("") == "empty"
    assert missing_kind("   ") == "empty"


def test_missing_kind_recognizes_sentinel_strings_case_insensitively():
    assert missing_kind("NULL") == "sentinel"
    assert missing_kind("n/a") == "sentinel"
    assert missing_kind("None") == "sentinel"
    assert missing_kind("-") == "sentinel"


def test_missing_kind_returns_none_for_a_real_value():
    assert missing_kind("larry@example.com") is None
    assert missing_kind("0") is None  # a real zero is not "nothing"


def _values(n, make):
    return [make(i) for i in range(n)]


def test_infers_email_type_with_full_confidence():
    values = _values(25, lambda i: f"user{i}@example.com")
    result = infer_column_type(values)
    assert result["type"] == "email"
    assert result["confidence"] == 1.0


def test_infers_integer_type_for_plain_numbers():
    values = _values(25, lambda i: str(i))
    result = infer_column_type(values)
    assert result["type"] == "integer"


def test_leading_zero_guard_reclassifies_zip_like_codes_as_integer_code():
    # Every value here matches \d+, but str(int("02134")) != "02134" --
    # the round-trip guard must catch this and refuse to call it "integer".
    values = _values(25, lambda i: f"{i:05d}")
    result = infer_column_type(values)
    assert result["type"] == "integer_code"


def test_infers_date_type_across_mixed_recognized_formats():
    values = ["2024-01-15", "01/16/2024", "2024-01-17"] * 10
    result = infer_column_type(values)
    assert result["type"] == "date"


def test_ambiguous_column_below_threshold_is_unclassified():
    # Half dates, half plain text -- neither clears the 90% bar.
    values = _values(30, lambda i: "2024-01-15" if i % 2 == 0 else f"note {i}")
    result = infer_column_type(values)
    assert result["type"] == "unclassified"
    assert result["confidence"] is None


def test_small_sample_is_insufficient_data_regardless_of_pattern():
    values = _values(5, lambda i: f"user{i}@example.com")  # all valid, but too few
    result = infer_column_type(values)
    assert result["type"] == "insufficient_data"


def test_name_role_comes_from_header_hint_not_value_pattern():
    # Free text can't be pattern-matched as "a name" -- the header is the
    # only signal this module trusts for that semantic role.
    values = _values(25, lambda i: f"Person {i}")
    result = infer_column_type(values, header_name="full_name")
    assert result["type"] == "name"

    result_no_hint = infer_column_type(values, header_name="notes")
    assert result_no_hint["type"] == "unclassified"


def test_canonicalize_date_reformats_recognized_formats_to_mm_dd_yyyy():
    assert canonicalize_date("2024-03-05") == "03/05/2024"
    assert canonicalize_date("05/03/2024") == "05/03/2024"


def test_iso_date_column_is_inferred_as_date_not_phone():
    # "2024-01-15" also satisfies the phone pattern (digits + hyphens).
    # Phone used to be checked first, so ISO date columns came back "phone".
    values = _values(25, lambda i: f"2024-01-{i + 1:02d}")
    assert infer_column_type(values, header_name="signup_date")["type"] == "date"


def test_bare_long_number_column_is_not_inferred_as_phone_without_a_header_hint():
    values = _values(25, lambda i: str(1_000_000 + i * 7))
    assert infer_column_type(values, header_name="order_id")["type"] == "integer"


def test_bare_digit_column_with_phone_header_is_still_phone():
    values = _values(25, lambda i: f"55512340{i:02d}")
    assert infer_column_type(values, header_name="mobile_number")["type"] == "phone"


def test_formatted_phone_column_is_phone_without_any_header_hint():
    values = _values(25, lambda i: f"819-600-{1300 + i}")
    assert infer_column_type(values, header_name="contact")["type"] == "phone"


def test_day_month_order_is_decided_from_unambiguous_values():
    assert detect_day_month_order(["25/03/2024", "05/03/2024"]) == DAY_FIRST
    assert detect_day_month_order(["03/25/2024", "05/03/2024"]) == MONTH_FIRST


def test_day_month_order_is_unknown_with_no_or_conflicting_evidence():
    assert detect_day_month_order(["05/03/2024", "2024-01-15", ""]) is None
    assert detect_day_month_order(["25/03/2024", "03/25/2024"]) is None


def test_ambiguous_date_follows_the_column_order_it_is_given():
    assert canonicalize_date("05/03/2024", DAY_FIRST) == "03/05/2024"
    assert canonicalize_date("05/03/2024", MONTH_FIRST) == "05/03/2024"
    assert canonicalize_date("5/3/2024", MONTH_FIRST) == "05/03/2024"


def test_ambiguous_date_is_never_rewritten_without_a_known_order():
    # Zero-padding "5/3/2024" to "05/03/2024" would silently commit to
    # month-first -- exactly the guess this function must not make.
    assert canonicalize_date("5/3/2024") == "5/3/2024"


def test_unambiguous_date_is_reformatted_regardless_of_column_order():
    assert canonicalize_date("25/03/2024") == "03/25/2024"
    assert canonicalize_date("25-03-2024", MONTH_FIRST) == "03/25/2024"


def test_canonicalize_date_leaves_unparseable_values_untouched():
    # Not our job to guess -- this should surface as a Validity failure
    # instead, not get silently rewritten into something that looks valid.
    assert canonicalize_date("not a date") == "not a date"


def test_canonicalize_date_passes_through_missing_values():
    assert canonicalize_date("") == ""
    assert math.isnan(canonicalize_date(float("nan")))
