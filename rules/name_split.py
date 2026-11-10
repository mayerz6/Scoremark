"""
Name split: a structural transformation, run on every file (upload or
sample) before anything is typed or scored.

A file with a single combined-name column ("name", "full_name",
"Customer Name", ...) and NO dedicated first/last-name column gets that
column replaced, in place, by two columns:

    firstname = the first word
    lastname  = everything after it (empty for a single-word name)

Same rule as the ETL tool's OrderDatasetTransformer, so the web app's
clean.csv and the ETL's final file come out with the same name columns.

Deliberately conservative about WHICH column it splits -- exact header
matches only. A substring rule would also split "username",
"company_name" or "product_name", which aren't a person's name. And a file
that already has a firstname or lastname column is left alone: any other
"name" column there is something else (a company, a product).

Nothing here invents or drops a value: joining firstname + " " + lastname
gives back the original name with its whitespace normalized. A missing
name (empty, or a placeholder like "NULL") stays missing in both columns.
"""

from __future__ import annotations

import pandas as pd

from .schema import missing_kind

FIRSTNAME = "firstname"
LASTNAME = "lastname"

#: Single combined-name headers that get split. Compared after
#: normalization, so "Full Name", "full-name" and "FULL_NAME" all match.
FULL_NAME_HEADERS = ("name", "full_name", "fullname", "customer_name", "contact_name")

#: Headers that mean the file already has a separate first or last name --
#: when any is present, nothing is split.
FIRST_LAST_HEADERS = (
    "firstname", "first_name", "fname", "given_name", "forename",
    "lastname", "last_name", "lname", "surname", "family_name",
)


def _normalize_header(text: str) -> str:
    return "_".join(str(text).strip().lower().replace("-", " ").replace("_", " ").split())


_FULL_NAME_SET = {_normalize_header(h) for h in FULL_NAME_HEADERS}
_FIRST_LAST_SET = {_normalize_header(h) for h in FIRST_LAST_HEADERS}


def find_full_name_column(columns) -> str | None:
    """The column to split, or None when the file shouldn't be split."""
    normalized = {column: _normalize_header(column) for column in columns}
    if any(n in _FIRST_LAST_SET for n in normalized.values()):
        return None
    for column, n in normalized.items():
        if n in _FULL_NAME_SET:
            return column
    return None


def split_name(value) -> tuple:
    """("Mary Ann  Smith") -> ("Mary", "Ann Smith"). Missing stays missing."""
    if missing_kind(value) is not None:
        # Keep the original (e.g. "NULL") in firstname so it's still counted
        # as a missing value, exactly as it was in the source column.
        return value, ""
    words = str(value).split()
    return words[0], " ".join(words[1:])


def split_full_name_column(
    df: pd.DataFrame,
    declared_schema: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, dict[str, str] | None, dict | None]:
    """
    Returns (df, declared_schema, report):
      - df: a copy with the name column replaced by firstname + lastname at
        the same position, or the original df when nothing was split.
      - declared_schema: with the source column's declared type carried
        over to both new columns (None stays None).
      - report: None when nothing was split, otherwise
        {"source_column", "into", "split_count", "single_word_count", "missing_count"}.
    """
    source = find_full_name_column(df.columns)
    if source is None:
        return df, declared_schema, None

    pairs = [split_name(v) for v in df[source].tolist()]
    position = list(df.columns).index(source)

    out = df.drop(columns=[source])
    out.insert(position, FIRSTNAME, [first for first, _ in pairs])
    out.insert(position + 1, LASTNAME, [last for _, last in pairs])

    if declared_schema is not None:
        declared_schema = dict(declared_schema)
        source_type = declared_schema.pop(source, None)
        if source_type is not None:
            declared_schema[FIRSTNAME] = source_type
            declared_schema[LASTNAME] = source_type

    missing = sum(1 for v in df[source].tolist() if missing_kind(v) is not None)
    single_word = sum(
        1 for (first, last), original in zip(pairs, df[source].tolist())
        if missing_kind(original) is None and not last
    )
    report = {
        "source_column": source,
        "into": [FIRSTNAME, LASTNAME],
        "split_count": len(pairs) - missing - single_word,
        "single_word_count": single_word,
        "missing_count": missing,
    }
    return out, declared_schema, report
