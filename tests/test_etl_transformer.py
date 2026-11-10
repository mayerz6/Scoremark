"""
Tests for the batch ETL tool's stage-1 transformer (etl/transform/transformer.py).
"""

import pytest

from etl.schema import DatasetSchema
from etl.transform.transformer import (
    BasicCleaningRule,
    CharacterSanitizationRule,
    EmailValidationRule,
    OrderDatasetTransformer,
    PhoneValidationRule,
)

# Same shape as datasets/reportage/order_dataset.py: a raw file whose
# single "name" column must come out as firstname + lastname.
NAME_SCHEMA = DatasetSchema(
    header=("firstname", "lastname", "email", "phone"),
    field_indices={"name": 0, "email": 1, "phone": 2},
    has_header=True,
)


@pytest.mark.parametrize("email", ["", None, "none", "null", "no email", '""'])
def test_record_with_no_email_is_valid(email):
    # Email is optional in this workflow -- a missing or placeholder email
    # must never reject the record (and previously crashed with TypeError).
    record = {"email": email}
    assert EmailValidationRule().apply(record) is record


def test_record_without_an_email_key_is_valid():
    assert EmailValidationRule().apply({"phone": "5551234567"}) is not None


def test_present_but_malformed_email_is_still_rejected():
    assert EmailValidationRule().apply({"email": "not-an-email"}) is None


def test_well_formed_email_passes():
    assert EmailValidationRule().apply({"email": "Larry@Example.com"}) is not None


@pytest.mark.parametrize(
    "raw_name, firstname, lastname",
    [
        ("Larry Mayers", "Larry", "Mayers"),
        ("Mary Ann  Smith", "Mary", "Ann Smith"),  # everything after the first word
        ("  Yasmin  ", "Yasmin", ""),  # single word -> no lastname
        ("", "", ""),
    ],
)
def test_name_column_is_split_into_firstname_and_lastname(raw_name, firstname, lastname):
    transformer = OrderDatasetTransformer(NAME_SCHEMA, rules=[])
    result = transformer.transform([raw_name, "x@example.com", "5551234567"])

    assert result["firstname"] == firstname
    assert result["lastname"] == lastname


def test_name_split_survives_the_stage_one_rules_with_an_empty_email():
    rules = [CharacterSanitizationRule(), BasicCleaningRule(), EmailValidationRule(), PhoneValidationRule()]
    transformer = OrderDatasetTransformer(NAME_SCHEMA, rules)

    result = transformer.transform(["Larry Mayers", "", "555-123-4567"])

    assert result is not None
    assert (result["firstname"], result["lastname"], result["email"]) == ("Larry", "Mayers", "")


# ---------- empty records ----------

from etl.report.rule_tracker import RuleTracker  # noqa: E402
from etl.transform.transformer import OrderDatasetTransformerStage2, is_empty_record  # noqa: E402


@pytest.mark.parametrize("row, empty", [
    (["", "", ""], True),
    ([" ", "\t", ""], True),
    (["", "", "x"], False),       # text in ANY column -- even an unmapped one -- is not empty
    (["NULL", "", ""], False),    # a placeholder is text in the file
])
def test_is_empty_record(row, empty):
    assert is_empty_record(row) is empty


@pytest.mark.parametrize("transformer_class", [OrderDatasetTransformer, OrderDatasetTransformerStage2])
def test_both_stages_reject_an_empty_record_under_its_own_name(transformer_class):
    tracker = RuleTracker()
    transformer = transformer_class(NAME_SCHEMA, rules=[], tracker=tracker)
    assert transformer.transform(["", "  ", ""]) is None
    assert tracker.failures == {"EmptyRecord": 1}
