"""
Tests for rules/name_split.py and its place in the web pipeline: a
combined name column becomes firstname + lastname on every file, unless
the file already has a first/last-name column.
"""

import io

import pandas as pd
import pytest

from app import app as flask_app
from rules.disposition import run_pipeline
from rules.name_split import find_full_name_column, split_full_name_column, split_name


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.mark.parametrize("value, expected", [
    ("Larry Mayers", ("Larry", "Mayers")),
    ("Mary Ann  Smith", ("Mary", "Ann Smith")),  # everything after the first word
    ("  Yasmin  ", ("Yasmin", "")),              # single word -> no lastname
    ("", ("", "")),
    ("NULL", ("NULL", "")),                      # placeholder stays (still counted missing)
])
def test_split_name_matches_the_etl_rule(value, expected):
    assert split_name(value) == expected


@pytest.mark.parametrize("header", ["name", "Name", "full_name", "Full Name", "full-name", "FULLNAME", "Customer Name", "contact_name"])
def test_full_name_headers_are_split(header):
    assert find_full_name_column(["id", header, "email"]) == header


@pytest.mark.parametrize("header", ["username", "company_name", "product_name", "hotel_name", "nickname"])
def test_name_like_headers_that_are_not_a_person_are_left_alone(header):
    assert find_full_name_column(["id", header, "email"]) is None


@pytest.mark.parametrize("existing", ["firstname", "First Name", "last_name", "surname", "given_name"])
def test_nothing_is_split_when_a_first_or_last_name_column_exists(existing):
    assert find_full_name_column([existing, "name", "email"]) is None


def test_split_columns_replace_the_source_in_place_and_carry_its_declared_type():
    df = pd.DataFrame({"id": ["1"], "full_name": ["Larry Mayers"], "email": ["l@x.com"]})
    out, schema, report = split_full_name_column(df, {"id": "text", "full_name": "name", "email": "email"})

    assert list(out.columns) == ["id", "firstname", "lastname", "email"]
    assert schema == {"id": "text", "firstname": "name", "lastname": "name", "email": "email"}
    assert report == {"source_column": "full_name", "into": ["firstname", "lastname"],
                      "split_count": 1, "single_word_count": 0, "missing_count": 0}
    assert list(df.columns) == ["id", "full_name", "email"]  # input not mutated


def test_file_without_a_name_column_is_untouched():
    df = pd.DataFrame({"email": ["l@x.com"]})
    out, schema, report = split_full_name_column(df, None)
    assert out is df and schema is None and report is None


def test_pipeline_splits_title_cases_and_reports_the_split():
    df = pd.DataFrame({"name": ["larry mayers", "Yasmin", "", "MARY ANN SMITH"], "email": ["a@x.com", "b@x.com", "c@x.com", "d@x.com"]})
    # Declared "name" type carries over to both halves, so both get Title Case.
    result = run_pipeline(df, declared_schema={"name": "name", "email": "email"})

    clean = result["clean_df"]
    assert list(clean.columns) == ["firstname", "lastname", "email", "was_autocorrected"]
    assert list(zip(clean["firstname"], clean["lastname"])) == [
        ("Larry", "Mayers"), ("Yasmin", ""), ("", ""), ("Mary", "Ann Smith"),
    ]
    assert result["report"]["transformations"]["name_split"]["single_word_count"] == 1
    # One row with a fixed name counts once, though both halves changed.
    assert result["report"]["structure"]["autocorrected_row_count"] == 2


def test_a_name_column_used_as_a_declared_key_becomes_both_halves():
    df = pd.DataFrame({"name": ["Larry Mayers", "larry mayers", "Jane Doe"]})
    result = run_pipeline(df, key_columns=["name"])
    assert result["report"]["uniqueness"]["key_columns"] == ["firstname", "lastname"]
    assert result["report"]["uniqueness"]["duplicate_row_count"] == 1


def test_web_upload_downloads_have_split_name_columns(client):
    content = b"name,email,phone\nLarry Mayers,l@x.com,5551234567\nYasmin,y@x.com,\n"
    data = {"file": (io.BytesIO(content), "people.csv")}
    body = client.post("/analyze", data=data, content_type="multipart/form-data").get_data(as_text=True)

    assert "Name split" in body
    run_id = body.split("/download/")[1].split("/")[0]
    clean = client.get(f"/download/{run_id}/clean.csv").get_data(as_text=True).splitlines()
    assert clean[0].startswith("firstname,lastname,email,phone")
    assert clean[1].startswith("Larry,Mayers,")
    assert clean[2].startswith("Yasmin,,")
    client.post(f"/delete/{run_id}")
