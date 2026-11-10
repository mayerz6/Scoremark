"""
Per-file encoding + delimiter detection used by main_folder_batch.py, so a
folder can mix files from different sources.
"""

import csv

import pytest

from etl.utils.encoding import detect_delimiter, detect_encoding
from main_folder_batch import build_pipeline

HEADER = ["name", "email", "telephone", "city"]


def _people(n=25):
    return [[f"Person{i} Last{i}", f"p{i}@example.com", f"05620201{i:02d}", "Town"] for i in range(n)]


def _write(path, encoding, delimiter, rows):
    with open(path, "w", newline="", encoding=encoding) as f:
        csv.writer(f, delimiter=delimiter).writerows(rows)


@pytest.mark.parametrize(
    "encoding, delimiter",
    [("utf-8", ","), ("utf-8-sig", ";"), ("utf-16", ","), ("utf-8", "\t"), ("utf-8", "|")],
)
def test_encoding_and_delimiter_are_detected_per_file(tmp_path, encoding, delimiter):
    path = tmp_path / "people.csv"
    _write(path, encoding, delimiter, [HEADER] + _people())

    detected = detect_encoding(str(path))
    assert detect_delimiter(str(path), detected) == delimiter
    # Whatever chardet names it, it must read the header back cleanly --
    # in particular with no byte-order mark glued to the first column.
    with open(path, encoding=detected, newline="") as f:
        assert next(csv.reader(f, delimiter=delimiter)) == HEADER


def test_ascii_and_empty_files_fall_back_to_utf8(tmp_path):
    ascii_file, empty_file = tmp_path / "a.csv", tmp_path / "e.csv"
    ascii_file.write_bytes(b"a,b\n1,2\n")
    empty_file.write_bytes(b"")
    assert detect_encoding(str(ascii_file)) == "utf-8"
    assert detect_encoding(str(empty_file)) == "utf-8"


@pytest.mark.parametrize("encoding, delimiter", [("utf-16", ","), ("utf-8-sig", ",")])
def test_batch_pipeline_splits_a_leading_name_column_in_any_encoding(tmp_path, encoding, delimiter):
    raw = tmp_path / "records" / "people.csv"
    raw.parent.mkdir()
    _write(raw, encoding, delimiter, [HEADER] + _people())
    (tmp_path / "confirmed_dataset_headers.py").write_text(
        "from etl.schema import DatasetSchema\n"
        "final_schema = DatasetSchema(header=('firstname', 'lastname', 'email', 'phone', 'city'), field_indices={})\n"
    )

    out, garbage = tmp_path / "out.csv", tmp_path / "garbage.csv"
    valid, rejected = build_pipeline(str(raw), str(out), str(garbage)).run()

    assert (valid, rejected) == (25, 0)
    with open(out, encoding="utf-8") as f:
        first = next(csv.DictReader(f))
    assert (first["firstname"], first["lastname"]) == ("Person0", "Last0")
