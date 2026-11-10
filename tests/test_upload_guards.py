"""
Unit tests for upload_guards.py -- pure functions, no Flask, no HTTP.
See tests/test_web_routes.py for the integration-level versions of the
same checks, driven through the real /analyze endpoint.
"""

import pytest

from upload_guards import (
    MAX_COLUMNS,
    MAX_FILE_SIZE_BYTES,
    MAX_ROWS,
    UploadRejected,
    validate_dataframe_shape,
    validate_file_size,
    validate_filename,
    validate_is_text_content,
)


def test_filename_without_csv_extension_is_rejected():
    with pytest.raises(UploadRejected):
        validate_filename("not_a_csv.txt")


def test_filename_with_no_extension_at_all_is_rejected():
    with pytest.raises(UploadRejected):
        validate_filename("no_extension")


def test_filename_with_csv_extension_is_accepted():
    validate_filename("real_data.csv")  # does not raise


def test_filename_extension_check_is_case_insensitive():
    validate_filename("REAL_DATA.CSV")  # does not raise


def test_empty_file_is_rejected():
    with pytest.raises(UploadRejected):
        validate_file_size(0)


def test_file_exactly_at_the_cap_is_accepted():
    validate_file_size(MAX_FILE_SIZE_BYTES)  # does not raise


def test_file_one_byte_over_the_cap_is_rejected():
    with pytest.raises(UploadRejected):
        validate_file_size(MAX_FILE_SIZE_BYTES + 1)


def test_text_content_is_accepted():
    validate_is_text_content(b"firstname,email\nLarry,larry@x.com\n")  # does not raise


def test_binary_content_with_a_null_byte_is_rejected():
    with pytest.raises(UploadRejected):
        validate_is_text_content(b"\x00\x01PNG fake header bytes here")


def test_row_count_at_the_cap_is_accepted():
    validate_dataframe_shape(MAX_ROWS, 5)  # does not raise


def test_row_count_over_the_cap_is_rejected():
    with pytest.raises(UploadRejected):
        validate_dataframe_shape(MAX_ROWS + 1, 5)


def test_column_count_at_the_cap_is_accepted():
    validate_dataframe_shape(100, MAX_COLUMNS)  # does not raise


def test_column_count_over_the_cap_is_rejected():
    with pytest.raises(UploadRejected):
        validate_dataframe_shape(100, MAX_COLUMNS + 1)


def test_decoded_utf16_text_is_not_mistaken_for_binary():
    from rules.io import decode_csv_bytes
    raw = "name,email\nLarry,l@x.com\n".encode("utf-16")
    assert b"\x00" in raw  # why checking raw bytes used to reject it
    validate_is_text_content(decode_csv_bytes(raw)[0])  # does not raise


def test_binary_content_is_still_rejected_after_decoding():
    from rules.io import decode_csv_bytes
    with pytest.raises(UploadRejected):
        validate_is_text_content(decode_csv_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")[0])
