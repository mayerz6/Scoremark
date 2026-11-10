import io as stdlib_io

import pytest

from rules.io import CsvStructureError, detect_delimiter, read_csv_as_text


def test_detects_comma_delimiter():
    content = "a,b,c\n1,2,3\n4,5,6\n"
    assert detect_delimiter(stdlib_io.StringIO(content)) == ","


def test_detects_semicolon_delimiter():
    content = "a;b;c\n1;2;3\n4;5;6\n"
    assert detect_delimiter(stdlib_io.StringIO(content)) == ";"


def test_detects_pipe_delimiter():
    content = "a|b|c\n1|2|3\n4|5|6\n"
    assert detect_delimiter(stdlib_io.StringIO(content)) == "|"


def test_read_csv_as_text_auto_detects_and_parses_semicolon_file():
    content = "name;email\nLarry Mayers;larry@x.com\n"
    df = read_csv_as_text(stdlib_io.StringIO(content))
    assert list(df.columns) == ["name", "email"]
    assert df.iloc[0]["email"] == "larry@x.com"


def test_read_csv_as_text_handles_a_delimiter_appearing_inside_quotes():
    # The exact shape that breaks a naive comma-only parser on a real
    # order export: a quoted field legitimately contains the delimiter.
    content = 'name;user_agent\nLarry;"Mozilla/5.0 (X11; Linux x86_64)"\n'
    df = read_csv_as_text(stdlib_io.StringIO(content))
    assert df.iloc[0]["user_agent"] == "Mozilla/5.0 (X11; Linux x86_64)"


def test_explicit_delimiter_override_skips_sniffing():
    content = "a,b\n1,2\n"
    df = read_csv_as_text(stdlib_io.StringIO(content), delimiter=",")
    assert list(df.columns) == ["a", "b"]


def test_ragged_row_raises_a_clear_structure_error_not_a_raw_traceback():
    # One row with an inconsistent field count among otherwise-consistent
    # rows -- a genuinely malformed file. (A single row with exactly one
    # MORE field than every other row is not actually an error to pandas:
    # it silently reinterprets the extra field as an index column. That
    # surprised me the first time I wrote this test with only one data
    # row -- it's why this one uses three, with the inconsistency in the
    # middle, matching the shape of the real failure this was built for.)
    content = "a,b\n1,2\n3,4,5\n6,7\n"
    with pytest.raises(CsvStructureError):
        read_csv_as_text(stdlib_io.StringIO(content), delimiter=",")


def test_a_row_of_only_delimiters_is_not_dropped_by_the_reader():
    # Pandas' skip_blank_lines (on by default) only skips a line with zero
    # characters -- a line that's delimiters-with-nothing-between-them is
    # not "blank" to the parser, and must not silently vanish here. What
    # happens to it quality-wise is disposition.py's decision, not io.py's.
    content = "a,b,c\n1,2,3\n,,\n"
    df = read_csv_as_text(stdlib_io.StringIO(content), delimiter=",")
    assert len(df) == 2
    assert df.iloc[1].tolist() == ["", "", ""]


def test_a_truly_blank_line_is_skipped_by_pandas_default_behavior():
    # This one IS skipped -- a genuinely empty line (no delimiters at all)
    # is what pandas' skip_blank_lines actually targets. Documented here so
    # the difference from the test above is a verified fact, not a guess.
    content = "a,b,c\n1,2,3\n\n4,5,6\n"
    df = read_csv_as_text(stdlib_io.StringIO(content), delimiter=",")
    assert len(df) == 2


# ---------- encodings, malformed rows, clear errors ----------

from rules.io import decode_csv_bytes, read_csv_rows  # noqa: E402


@pytest.mark.parametrize("encoding", ["utf-16", "utf-8-sig", "cp1252", "utf-8"])
def test_common_encodings_decode_to_the_same_text(encoding):
    text = "name,city\nJosé,Montréal\n"
    decoded, _ = decode_csv_bytes(text.encode(encoding))
    assert decoded == text  # no BOM left on the first header, accents intact


def test_utf16_file_reads_with_a_clean_first_header():
    result = read_csv_rows(stdlib_io.BytesIO("name,email\nLarry,l@x.com\n".encode("utf-16")))
    assert list(result.dataframe.columns) == ["name", "email"]


def test_malformed_row_is_set_aside_and_the_rest_still_parse():
    content = "name,email\nLarry,l@x.com\nAlamo, Kamal,k@x.com\nJane,j@x.com\n"
    result = read_csv_rows(stdlib_io.StringIO(content))

    assert result.dataframe["name"].tolist() == ["Larry", "Jane"]
    # Original data-row positions survive, so garbage numbering stays true.
    assert result.dataframe.index.tolist() == [0, 2]
    [bad] = result.malformed_rows
    assert (bad.row_number, bad.line_number, bad.found_fields, bad.expected_fields) == (1, 3, 3, 2)
    assert bad.raw == "Alamo, Kamal,k@x.com"
    assert result.total_rows == 3


def test_short_rows_are_padded_and_trailing_empty_fields_are_ignored():
    content = "a,b,c\n1,2\n4,5,6,\n"
    result = read_csv_rows(stdlib_io.StringIO(content), delimiter=",")
    assert result.dataframe.values.tolist() == [["1", "2", ""], ["4", "5", "6"]]
    assert result.malformed_rows == []


def test_duplicate_and_blank_headers_get_unique_names():
    result = read_csv_rows(stdlib_io.StringIO("a,a,,b\n1,2,3,4\n"), delimiter=",")
    assert list(result.dataframe.columns) == ["a", "a.1", "Unnamed: 2", "b"]


@pytest.mark.parametrize("content", ["", "\n\n", "  \n", ",,\n"])
def test_file_with_no_header_is_a_clear_error_naming_the_file(content):
    with pytest.raises(CsvStructureError) as error:
        read_csv_rows(stdlib_io.StringIO(content), source_name="upload.csv")
    assert "upload.csv" in str(error.value)
    assert "BytesIO" not in str(error.value)


def test_unnamed_in_memory_upload_never_shows_a_python_repr():
    with pytest.raises(CsvStructureError) as error:
        read_csv_rows(stdlib_io.BytesIO(b"\n"))
    assert "<_io" not in str(error.value)
