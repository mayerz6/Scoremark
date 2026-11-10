"""
Tests for the hybrid (auto-detected schema) ETL path: column detection in
etl/schema_detection.py and header handling in etl/extract/csv_extractor.py.
"""

import csv

from etl.extract.csv_extractor import CSVExtractor
from etl.load.csv_loader import CSVLoader, GarbageLoader
from etl.schema import DatasetSchema
from etl.schema_detection import detect_schema
from etl.transform.transformer import (
    EmailValidationRule,
    OrderDatasetTransformer,
    OrderDatasetTransformerStage2,
    SchemaEnforcementRule,
)
from etl_pipeline import Pipeline

FINAL_SCHEMA = DatasetSchema(
    header=("firstname", "lastname", "email", "phone"),
    field_indices={"firstname": 0, "lastname": 1, "email": 2, "phone": 3},
    has_header=True,
)


def _sample_rows(n=25):
    return [[f"Person{i} Last{i}", f"p{i}@example.com", "h", f"05620201{i:02d}", ""] for i in range(n)]


# ---------- detection: combined name column ----------

def test_single_name_column_is_mapped_to_name_for_splitting():
    header = ["name", "email", "password", "phone", "provider"]
    schema, confidence = detect_schema(header, _sample_rows())

    assert schema.field_indices["name"] == 0
    # Not claimed by firstname via the "name" in "firstname" substring rule.
    assert "firstname" not in schema.field_indices
    assert "lastname" not in schema.field_indices
    assert confidence["firstname"]["method"] == "split_from_name"
    assert confidence["lastname"]["method"] == "split_from_name"


def test_full_name_header_variant_is_recognized():
    header = ["Full_Name", "email", "password", "phone", "provider"]
    schema, _ = detect_schema(header, _sample_rows())
    assert schema.field_indices["name"] == 0


def test_dedicated_first_and_last_columns_take_priority_over_a_name_column():
    # A separate "name" column (e.g. a company/product name) must not be
    # split over real firstname/lastname values.
    header = ["firstname", "lastname", "name", "email", "phone"]
    rows = [[f"F{i}", f"L{i}", f"Acme {i}", f"p{i}@example.com", f"05620201{i:02d}"] for i in range(25)]
    schema, _ = detect_schema(header, rows)

    assert schema.field_indices["firstname"] == 0
    assert schema.field_indices["lastname"] == 1
    assert "name" not in schema.field_indices


def test_name_like_headers_that_are_not_a_person_name_are_not_split():
    header = ["username", "email", "password", "phone", "provider"]
    schema, _ = detect_schema(header, _sample_rows())
    assert "name" not in schema.field_indices


def test_detected_name_column_is_split_by_the_transformer():
    header = ["name", "email", "password", "phone", "provider"]
    schema, _ = detect_schema(header, _sample_rows())

    result = OrderDatasetTransformer(schema, rules=[]).transform(
        ["Mary Ann Smith", "m@example.com", "h", "0562020100", ""]
    )
    assert (result["firstname"], result["lastname"]) == ("Mary", "Ann Smith")


# ---------- extractor: header handling ----------

def _write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def test_extractor_skips_the_header_row_when_schema_has_one(tmp_path):
    path = tmp_path / "in.csv"
    _write(path, [["firstname", "lastname", "email", "phone"], ["Larry", "Mayers", "l@x.com", "5551234567"]])

    rows = list(CSVExtractor(str(path), FINAL_SCHEMA, delimiter=",", encoding="utf-8").extract())
    assert rows == [["Larry", "Mayers", "l@x.com", "5551234567"]]


def test_extractor_skips_banner_rows_before_treating_the_next_row_as_header(tmp_path):
    path = tmp_path / "in.csv"
    _write(path, [["Exported 2026-11-10"], ["firstname", "lastname", "email", "phone"], ["A", "B", "a@x.com", "1"]])

    rows = list(CSVExtractor(str(path), FINAL_SCHEMA, delimiter=",", encoding="utf-8").extract())
    assert rows == [["A", "B", "a@x.com", "1"]]


def test_extractor_keeps_the_first_row_when_schema_has_no_header(tmp_path):
    path = tmp_path / "in.csv"
    _write(path, [["Larry", "Mayers", "l@x.com", "5551234567"]])
    no_header = DatasetSchema(FINAL_SCHEMA.header, FINAL_SCHEMA.field_indices, has_header=False)

    rows = list(CSVExtractor(str(path), no_header, delimiter=",", encoding="utf-8").extract())
    assert rows == [["Larry", "Mayers", "l@x.com", "5551234567"]]


def test_two_stage_run_never_copies_the_header_into_the_final_file(tmp_path):
    raw = tmp_path / "raw.csv"
    _write(raw, [["name", "email", "password", "phone", "provider"]] + _sample_rows())
    with open(raw, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        schema, _ = detect_schema(header, list(reader))

    processed, final = tmp_path / "processed.csv", tmp_path / "final.csv"
    Pipeline(CSVExtractor(str(raw), schema, delimiter=",", encoding="utf-8"),
             OrderDatasetTransformer(schema, [EmailValidationRule()]),
             CSVLoader(str(processed), FINAL_SCHEMA.header), GarbageLoader(str(tmp_path / "g1.csv"))).run()
    Pipeline(CSVExtractor(str(processed), FINAL_SCHEMA, delimiter=",", encoding="utf-8"),
             OrderDatasetTransformerStage2(FINAL_SCHEMA, [SchemaEnforcementRule(FINAL_SCHEMA)]),
             CSVLoader(str(final), FINAL_SCHEMA.header), GarbageLoader(str(tmp_path / "g2.csv"))).run()

    with open(final, encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert rows[0] == list(FINAL_SCHEMA.header)
    assert list(FINAL_SCHEMA.header) not in rows[1:]
    assert len(rows) - 1 == 25
    assert rows[1][:2] == ["Person0", "Last0"]
    # The raw header row is no longer mis-filed as a garbage record.
    assert not (tmp_path / "g1.csv").exists()


def test_sparse_phone_column_is_still_found_by_its_exact_header():
    # Only 10 phones in 25 rows: too few for content matching (MIN_SAMPLE_SIZE),
    # but the header says exactly what it is.
    header = ["name", "email", "password", "phone", "provider"]
    rows = [[f"P{i} L{i}", f"p{i}@example.com", "h", f"05620201{i:02d}" if i < 10 else "", ""] for i in range(25)]
    schema, confidence = detect_schema(header, rows)
    assert schema.field_indices["phone"] == 3
    assert confidence["phone"]["method"] == "header_exact"


def test_content_role_never_falls_back_to_a_substring_header_match():
    header = ["name", "email", "hotel_name"]  # "tel" is inside "hotel_name"
    rows = [[f"P{i}", f"p{i}@example.com", "Ritz"] for i in range(25)]
    schema, _ = detect_schema(header, rows)
    assert "phone" not in schema.field_indices
