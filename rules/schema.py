"""
Schema resolution: deciding what each column "is" before any rule can score it.

Two paths, per scoremark_project.md's "Schema Resolution" section:
  - declared:  the caller already knows the type (canned samples -- we wrote
               the file, we know its columns). Nothing in this module runs.
  - inferred:  statistical type inference over the column's own values, for
               a stranger's uploaded CSV where no schema was ever declared.

Everything below implements the *inferred* path precisely as specified:
checkers tried most-specific-first, a 90% confidence threshold, a 20-value
minimum sample size, and a round-trip guard against the leading-zero bug.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import pandas as pd

MIN_SAMPLE_SIZE = 20
CONFIDENCE_THRESHOLD = 0.90

# Non-empty strings that mean "nothing," dressed up as data.
NULL_SENTINELS = {"null", "n/a", "na", "none", "-"}

DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%m-%d-%Y",
)

#: Year-first formats -- never ambiguous about which part is the day.
_YEAR_FIRST_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")
#: Day/month-first formats, split by which order they assume. A value like
#: "05/03/2024" parses under BOTH groups, and nothing in the value itself
#: says which one was meant -- only the rest of its column can.
_MONTH_FIRST_FORMATS = ("%m/%d/%Y", "%m-%d-%Y")
_DAY_FIRST_FORMATS = ("%d/%m/%Y", "%d-%m-%Y")

MONTH_FIRST = "month_first"
DAY_FIRST = "day_first"

#: Header fragments that mark a column as holding phone numbers -- the only
#: way to tell a column of bare-digit phone numbers apart from a column of
#: bare-digit IDs, since the values themselves look identical.
_PHONE_HEADER_HINTS = ("phone", "tel", "mobile", "cell", "fax")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^[\d\s\-().+]{7,20}$")
_INTEGER_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_BOOLEAN_VALUES = {"true", "false", "yes", "no"}


def missing_kind(value: Any) -> str | None:
    """
    Classifies a single cell as 'empty', 'sentinel', or None (not missing).

    Both kinds are missing (Completeness and occupancy count them; neither
    is invalid). The distinction still matters for one rule: an *empty
    record* -- a row that's only delimiters -- is one where every cell is
    'empty'. A row of "NULL"s has text in it; a row of ",,,," doesn't.

    Uses pandas.isna() rather than a manual None/NaN check so this behaves
    correctly regardless of which "nothing" pandas produced (None, float
    NaN, NaT, pandas' nullable NA) -- see io.read_csv_as_text() for the other
    half of making this distinction actually reachable in the first place.
    """
    if pd.isna(value):
        return "empty"

    text = str(value).strip()
    if text == "":
        return "empty"
    if text.lower() in NULL_SENTINELS:
        return "sentinel"
    return None


def is_missing(value: Any) -> bool:
    return missing_kind(value) is not None


def _is_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


def _is_phone(value: str) -> bool:
    digit_count = sum(ch.isdigit() for ch in value)
    return bool(_PHONE_RE.match(value)) and 7 <= digit_count <= 15


def _is_date(value: str) -> bool:
    for fmt in DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def _is_boolean(value: str) -> bool:
    return value.strip().lower() in _BOOLEAN_VALUES


def _is_integer(value: str) -> bool:
    return bool(_INTEGER_RE.match(value))


def _is_float(value: str) -> bool:
    return bool(_FLOAT_RE.match(value))


# Order matters: most specific first. A column of "1"/"0" values should
# never be read as a float just because floats are checked last; a column
# of emails should never fall through to "text" just because text always
# matches last. See the module docstring in scoremark_project.md's teaching
# section for why ordering by specificity (not raw match rate) is the
# correct approach here.
#
# Date is checked BEFORE phone on purpose: the phone pattern (digits plus
# "-", ".", "(", ")", spaces) also matches ISO dates like "2024-01-15", so
# with phone first, the single most common date format was classified as a
# phone column -- never date-validated, never canonicalized, and eligible
# to be picked as the dedupe key. No real phone number parses as a date, so
# the reverse order costs nothing.
CHECKERS: tuple[tuple[str, Any], ...] = (
    ("email", _is_email),
    ("date", _is_date),
    ("phone", _is_phone),
    ("boolean", _is_boolean),
    ("integer", _is_integer),
    ("float", _is_float),
)

#: A checker function for every type this module can classify a column as,
#: used later by validity.py to flag individual bad values within a column
#: whose type has already been decided. "integer_code" reuses the integer
#: shape check (still digits-only) -- the round-trip guard above is only
#: about whether it's *safe to treat the column as numeric*, not about what
#: counts as a valid value within it.
CHECKER_BY_TYPE: dict[str, Any] = {name: fn for name, fn in CHECKERS}
CHECKER_BY_TYPE["integer_code"] = _is_integer


def infer_column_type(values: list[Any], header_name: str = "") -> dict:
    """
    Decides one column's type from its own values (see Schema Resolution in
    scoremark_project.md for the full rationale). Returns a dict with at
    least a "type" and "confidence" key.

    Known, documented limitation: this has no reliable value-pattern way to
    detect "this text column holds human names" -- names are free text,
    indistinguishable from any other text column by pattern alone. The only
    signal used for that is the column header itself (see the "name" branch
    below). A future iteration could strengthen this (e.g. a name-frequency
    dictionary), but header hinting is the honest, simple choice for v1.
    """
    non_missing = [str(v).strip() for v in values if not is_missing(v)]

    if len(non_missing) < MIN_SAMPLE_SIZE:
        return {"type": "insufficient_data", "confidence": None}

    for type_name, checker in CHECKERS:
        matches = sum(1 for v in non_missing if checker(v))
        rate = matches / len(non_missing)
        if rate >= CONFIDENCE_THRESHOLD:
            if type_name == "phone" and _is_mostly_bare_numbers(non_missing) \
                    and not _header_hints_phone(header_name):
                # Bare 7-15 digit numbers (order IDs, account numbers,
                # amounts like "1234.5678") pass the phone pattern too.
                # Without a phone-ish header there's no evidence they're
                # phone numbers -- let integer/float decide instead.
                continue
            if type_name == "integer":
                # Leading-zero guard: a ZIP code or account number matches
                # \d+ perfectly, but str(int("02134")) != "02134". Columns
                # that fail this round-trip are identifiers, not numbers --
                # classify them separately so nothing ever casts them to int.
                roundtrip_ok = all(str(int(v)) == v for v in non_missing if checker(v))
                if not roundtrip_ok:
                    return {"type": "integer_code", "confidence": rate}
            return {"type": type_name, "confidence": rate}

    if "name" in header_name.lower():
        return {"type": "name", "confidence": None, "source": "header_hint"}

    return {"type": "unclassified", "confidence": None}


def _is_mostly_bare_numbers(values: list[str]) -> bool:
    bare = sum(1 for v in values if _is_integer(v) or _is_float(v))
    return bare / len(values) >= CONFIDENCE_THRESHOLD


def _header_hints_phone(header_name: str) -> bool:
    header = header_name.lower()
    return any(hint in header for hint in _PHONE_HEADER_HINTS)


def detect_day_month_order(values: list[Any]) -> str | None:
    """
    Decides, for a whole column, whether its day/month-first dates are
    MONTH_FIRST (US, "03/25/2024") or DAY_FIRST ("25/03/2024").

    Only *unambiguous* values count as evidence: "25/03/2024" can only be
    day-first, "03/25/2024" can only be month-first, while "05/03/2024"
    could be either and proves nothing. Returns None when there's no
    evidence at all, or when the column contains evidence for both orders
    (mixed sources) -- in either case no ambiguous value can be safely
    reinterpreted.
    """
    month_first_evidence = 0
    day_first_evidence = 0

    for value in values:
        if is_missing(value):
            continue
        text = str(value).strip()
        as_month_first = _parse_with(text, _MONTH_FIRST_FORMATS)
        as_day_first = _parse_with(text, _DAY_FIRST_FORMATS)
        if as_month_first and not as_day_first:
            month_first_evidence += 1
        elif as_day_first and not as_month_first:
            day_first_evidence += 1

    if month_first_evidence and not day_first_evidence:
        return MONTH_FIRST
    if day_first_evidence and not month_first_evidence:
        return DAY_FIRST
    return None


def canonicalize_date(value: Any, day_month_order: str | None = None) -> Any:
    """
    Reformats a recognized date string to the canonical MM/DD/YYYY.

    day_month_order: the column-level order from detect_day_month_order().
    A value that could be read either way ("05/03/2024": 5 March or 3 May?)
    is only reformatted when this is known. Without it, the value is left
    exactly as it was -- reformatting it would mean guessing, and a wrong
    guess silently produces a valid-looking but wrong date. Values that can
    only be read one way (year-first, or a day above 12) are always
    reformatted, since they carry their own answer.

    Returns the value unchanged if it doesn't parse under any known format
    -- an unparseable date is a Validity failure, not something Consistency
    should guess at fixing.
    """
    if is_missing(value):
        return value

    text = str(value).strip()

    for fmt in _YEAR_FIRST_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue

    month_first = _parse_with(text, _MONTH_FIRST_FORMATS)
    day_first = _parse_with(text, _DAY_FIRST_FORMATS)

    if month_first and day_first and month_first != day_first:
        # Genuinely ambiguous -- only the column can settle it.
        if day_month_order == DAY_FIRST:
            chosen = day_first
        elif day_month_order == MONTH_FIRST:
            chosen = month_first
        else:
            return value
    else:
        chosen = month_first or day_first

    return chosen.strftime("%m/%d/%Y") if chosen else value


def _parse_with(text: str, formats: tuple[str, ...]) -> datetime | None:
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def is_invalid_value(value: Any, column_type: str) -> bool:
    """
    The single source of truth for "is this one cell a Validity failure,"
    shared by validity.py's aggregate scoring and disposition.py's per-row
    routing -- both must agree on this or the report's numbers and the
    garbage file's row count could silently drift apart.

    A missing value is never invalid -- whether truly empty or a null
    placeholder ("NULL", "N/A", ...). Fields are optional: a missing value
    is Completeness's (and occupancy's) concern only, never a reason to
    reject a row. Placeholders count as missing, not malformed, because
    that's how many exports write "no value" (e.g. a database dump's NULL).
    A column type with no registered checker (unscored types: "text",
    "name", "unclassified", "insufficient_data") never flags anything.
    """
    if column_type not in CHECKER_BY_TYPE:
        return False

    if missing_kind(value) is not None:
        return False

    checker = CHECKER_BY_TYPE[column_type]
    return not checker(str(value).strip())
