from typing import Dict, Any, Optional
from datetime import datetime
import re

from .base import Transformer
from etl.schema import DatasetSchema
from datasets.samples.order_dataset import schema


class LeakTransformer():
    def __init__(self, schema: DatasetSchema):
        self.schema = schema

    def transform(self, record: Dict[str, Any]) -> Dict[str, Any]:
        transformed = {}

        for standard_field, raw_field in self.schema.field_indices.items():
            value = record.get(raw_field, "")
            transformed[standard_field] = value.strip() if value else ""

        return transformed


EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

class BasicCleaningRule:
    def apply(self, record: Dict[str, str]) -> Optional[Dict[str, str]]:
        for k, v in record.items():
            if isinstance(v, str):
                record[k] = v.strip().replace('"', '').replace("'", "")
        return record


class DateNormalizationRule:

    def __init__(self, field="dob", output_format="%m/%d/%Y", strict=False):
        self.field = field
        self.output_format = output_format
        self.strict = strict

        self.formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y/%m/%d"
        ]

        self.invalid_tokens = {"none", "null", "nan", ""}

    def parse_date(self, value: str) -> Optional[str]:

        value = value.strip().lower()

        if value in self.invalid_tokens:
            return None

        # Remove unwanted characters
        value = re.sub(r"[\"']", "", value)

        for fmt in self.formats:
            try:
                dt = datetime.strptime(value, fmt)
                return dt.strftime(self.output_format)
            except ValueError:
                continue

        return None

    def apply(self, record):

        raw_value = record.get(self.field)

        if not raw_value:
            return record

        parsed = self.parse_date(raw_value)

        if parsed is None:
            if self.strict:
                return None   # reject record
            else:
                record[self.field] = ""
                return record

        record[self.field] = parsed
        return record

class EmailValidationRule:

    @staticmethod
    def to_lower(s: Optional[str]) -> Optional[str]:
        return s.lower() if s else None

    def apply(self, record):
        # Lowercase and strip placeholders BEFORE removing spaces -- removing
        # spaces first turned "no email" into "noemail", which then failed
        # validation instead of being recognized as "no email given".
        email = self.to_lower(record.get("email")) or ""
        email = email.replace("no email", "").replace("none", "").replace("null", "")
        email = email.replace(" ", "").replace('"', '').replace("'", "")

        # Email is optional in this workflow: a record with no email (or
        # only a placeholder like "none"/"null") is still a valid record.
        # Only a present, malformed email is a reason to reject it.
        if not email:
            return record

        if not EMAIL_PATTERN.fullmatch(email):
            return None
        return record

class PhoneValidationRule:

    def apply(self, record):

        for field in ["phone", "mobile"]:

            value = record.get(field)
            
            if value:
                value = value.strip()
                # Normalize phone (remove formatting)
                value = re.sub(r"\D", "", value)

                if(len(value) < 7 or len(value) > 15):
                    return None
                
                record[field] = value

        # phone = record.get("phone")
        # mobile = record.get("mobile")

        # if not phone or not mobile:
        #     return record

        # phone = phone.strip()
        # mobile = mobile.strip()

        # if not self.PHONE_PATTERN.fullmatch(phone):
        #     return None

        # Normalize phone (remove formatting)
        # phone = re.sub(r"[().+ ]", "", phone)
        # phone = re.sub(r"\D", "", phone)
        # mobile = re.sub(r"\D", "", mobile)

        return record

class SchemaEnforcementRule:

    def __init__(self, schema):
        self.schema = schema

    def apply(self, record):

        clean = {}

        for field in self.schema.header:
            clean[field] = record.get(field, "")

        return clean

class AddressCleaningRule:

    def apply(self, record):

        address = record.get("address")

        if not address:
            return record

        address = address.replace('"', '').replace("'", "").replace(",", " ").replace(".", " ").replace("-", " ")
        address = address.strip()

        address = re.sub(r"\s+", " ", address).strip()

        record["address"] = self.to_camel_case(address)

        return record
    
    def to_camel_case(self, s: str) -> str:
        return ' '.join(word.capitalize() for word in s.split()) if s else None


class CharacterSanitizationRule:

    def __init__(self, chars=None):

        if chars is None:
            chars = ["`", "'", '"', "\\", "NULL", "Null", "None", "Unknown"]

        self.chars = chars

    def apply(self, record):

        for field, value in record.items():

            if not isinstance(value, str):
                continue

            for c in self.chars:
                value = value.replace(c, "")

            record[field] = value

        return record

class MinFieldRule:
    def __init__(self, min_non_empty: int):
        self.min_non_empty = min_non_empty

    def apply(self, record):
        count = sum(1 for v in record.values() if v)
        return record if count >= self.min_non_empty else None
    
EMPTY_RECORD = "EmptyRecord"


def is_empty_record(raw_record: list[str]) -> bool:
    """
    True for a row that's only delimiters -- every field, mapped or not,
    is empty or whitespace. Such a row is garbage by definition, rejected
    before any rule runs and recorded under its own name ("EmptyRecord")
    so the rule-failure chart tells it apart from a sparse-but-real row
    that MinFieldRule rejects. Checked on the RAW row: a record whose
    mapped fields happen to be empty but which has text in other columns
    is not empty.
    """
    return not any(str(cell).strip() for cell in raw_record)


def _reject_if_empty(raw_record, tracker) -> bool:
    if is_empty_record(raw_record):
        if tracker:
            tracker.record_failure(EMPTY_RECORD)
        return True
    return False


class OrderDatasetTransformer:
    def __init__(self, schema, rules, tracker=None):
        self.schema = schema
        self.rules = rules
        self.tracker = tracker

    def transform(self, raw_record: list[str]) -> Optional[Dict[str, str]]:
        if _reject_if_empty(raw_record, self.tracker):
            return None

        # Map standard fields
        transformed = {}

        for field, idx in self.schema.field_indices.items():

            if idx < len(raw_record):
                transformed[field] = raw_record[idx].strip()
            else:
                transformed[field] = ""

        # Split name into first and last names if applicable
        if "name" in transformed:
            name_parts = transformed["name"].split()
            if len(name_parts) >= 2:
                transformed["firstname"] = name_parts[0]
                transformed["lastname"] = " ".join(name_parts[1:])
            else:
                transformed["firstname"] = transformed["name"]
                transformed["lastname"] = ""
                
        # Construct address
        # address_fields = ["city", "street", "house", "entry", "floor", "apartments"]

        # address_parts = []

        # for field in address_fields:
        #     idx = self.schema.field_indices[field]
        #     value = raw_record[idx] if idx < len(raw_record) else ""
        #     address_parts.append(value.strip())

        # transformed["address"] = " ".join(p for p in address_parts if p)

        # Apply rules
        for rule in self.rules:
            # transformed = rule.apply(transformed)
            transformed = rule.apply(transformed)
            if transformed is None:
                if self.tracker:
                    self.tracker.record_failure(rule.__class__.__name__)

                return None

        return transformed

class OrderDatasetTransformerStage2:
    def __init__(self, schema, rules, tracker=None):
        self.schema = schema
        self.rules = rules
        self.tracker = tracker

    def transform(self, raw_record: list[str]) -> Optional[Dict[str, str]]:
        if _reject_if_empty(raw_record, self.tracker):
            return None

        # Map standard fields
        transformed = {}

        for field, idx in self.schema.field_indices.items():

            if idx < len(raw_record):
                transformed[field] = raw_record[idx].strip()
            else:
                transformed[field] = ""

        # Apply rules
        for rule in self.rules:
            # transformed = rule.apply(transformed)
            transformed = rule.apply(transformed)
            if transformed is None:
                if self.tracker:
                    self.tracker.record_failure(rule.__class__.__name__)

                return None

        return transformed