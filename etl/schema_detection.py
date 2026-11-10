"""
Content + header based column-role detection.

This is the hybrid piece: it produces a DatasetSchema automatically instead
of one being hand-written (datasets/samples/order_dataset.py's `schema` is
the hand-written version this is meant to reproduce). Everything downstream
-- CSVExtractor, OrderDatasetTransformer, the rule classes -- is unchanged;
they only ever consume a DatasetSchema's field_indices and never cared how
those indices were decided. That seam is what makes this a hybrid rather
than a rewrite: the fixed-schema tool's entire batch machinery (two stages,
dedup, independent validation, provenance) stays exactly as it is in
docs/FIXED_SCHEMA_ETL_TUTORIAL.md. Only the step that used to be "someone
hand-counts column positions and writes a Python dict" is automated.

Deliberately self-contained, no import from the portfolio's rules/ package
-- this tool and that one are headed for separate GitHub repos, and a
cross-repo import would make neither one runnable on its own.

Two signals, used in priority order:

  1. Content pattern matching, for the two roles that have a reliable one
     (email, phone) -- the strongest evidence, because it's checking the
     actual data, not trusting a label.
  2. Header name + synonym matching, for every role -- required for
     free-text roles (a name or an address has no detectable value
     pattern), and used as the only signal once the content-checkable
     roles have already claimed their columns.

A column, once claimed by either signal, is removed from consideration for
every other role -- two roles can never be assigned to the same column.
"""

from __future__ import annotations

import re

from .schema import DatasetSchema

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value.strip()))


def _is_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return 7 <= len(digits) <= 15


#: Roles with a content checker are resolved first (Pass 1, strongest
#: evidence). Everything else is header-only (Pass 2).
CONTENT_CHECKERS = {
    "email": _is_email,
    "phone": _is_phone,
}

#: Lowercase fragments that count as a header match for each role. A
#: header matches a role if any synonym appears in it (or it in a synonym)
#: -- e.g. "telephone" matches "phone" via the "phone" synonym being a
#: substring of the header text.
ROLE_SYNONYMS: dict[str, list[str]] = {
    "firstname": ["firstname", "first_name", "fname", "given_name"],
    "lastname": ["lastname", "last_name", "lname", "surname"],
    "email": ["email", "e_mail", "e-mail"],
    "phone": ["phone", "telephone", "mobile", "tel"],
    "address": ["address", "street", "addr"],
    "city": ["city", "town"],
    "zipcode": ["zip", "zipcode", "postcode", "postal"],
    "ip_address": ["ip_address", "ipaddress", "ip"],
}

#: Exact (lowercased) headers for a single combined-name column. Not a
#: regular role in ROLE_SYNONYMS on purpose: it's an *input* column, not an
#: output field. When a file has one of these instead of separate
#: first/last-name columns, it's mapped to the "name" index, and
#: OrderDatasetTransformer splits it into firstname + lastname -- the same
#: path the hand-written datasets/reportage/order_dataset.py schema takes.
#: Exact match only: a substring rule would also catch "username",
#: "company_name", "product_name", etc.
FULL_NAME_HEADERS = ("name", "full_name", "fullname", "full name", "customer_name", "contact_name")

#: Minimum non-empty values before a content match rate is trusted at all
#: -- same spirit as rules/schema.py's MIN_SAMPLE_SIZE, prevents a handful
#: of coincidentally-email-shaped values from winning a column.
MIN_SAMPLE_SIZE = 20

#: A column must match a content checker at least this reliably to be
#: assigned that role. Looser than rules/schema.py's 90% on purpose -- a
#: real-world export like this one has enough genuine garbage mixed in
#: (blank fields, the pre-existing "?????" mojibake) that a stricter bar
#: risked rejecting the correct column outright. 85% was chosen by running
#: it against this exact file and checking the result, not guessed.
CONTENT_MATCH_THRESHOLD = 0.85


def _normalize_header(text: str) -> str:
    """"First Name", "first-name" and "first_name" all compare equal."""
    return "_".join(text.strip().lower().replace("-", " ").replace("_", " ").split())


def _exact_header_names(role: str) -> set[str]:
    """
    Headers that count as an exact match for a role. A role with no entry
    in ROLE_SYNONYMS -- any field added by hand to a dataset's
    confirmed_dataset_headers.py, e.g. "password" or "provider" -- matches
    a column whose header is the field name itself. Exact only, never
    substring: a custom "provider" must not grab "provider_id".
    """
    return {_normalize_header(s) for s in ROLE_SYNONYMS.get(role, [role])}


def _header_matches(header: str, role: str) -> bool:
    header_lower = header.strip().lower()
    return any(
        synonym in header_lower or header_lower in synonym
        for synonym in ROLE_SYNONYMS.get(role, [])
    )


def _content_match_rate(values: list[str], checker) -> float:
    non_empty = [v for v in values if v][:500]  # capped sample, cheap even on huge files
    if len(non_empty) < MIN_SAMPLE_SIZE:
        return 0.0
    matches = sum(1 for v in non_empty if checker(v))
    return matches / len(non_empty)


def detect_schema(
    header: list[str],
    sample_rows: list[list[str]],
    roles: tuple[str, ...] = tuple(ROLE_SYNONYMS.keys()),
) -> tuple[DatasetSchema, dict]:
    """
    header: the raw header row, as read by csv.reader (list[str]).
    sample_rows: a sample of raw data rows, same column count as header.
    roles: which standardized fields to resolve -- defaults to every role
        this module knows about.

    Returns (schema, confidence) -- confidence records, per role, which
    signal decided it and the evidence for that decision, so a report can
    show its reasoning rather than just its conclusion.
    """
    columns_by_index = {
        idx: [row[idx] for row in sample_rows if idx < len(row)]
        for idx in range(len(header))
    }

    claimed: dict[int, str] = {}
    field_indices: dict[str, int] = {}
    confidence: dict[str, dict] = {}

    content_roles = [r for r in roles if r in CONTENT_CHECKERS]
    header_only_roles = [r for r in roles if r not in CONTENT_CHECKERS]

    # Pass 1: content pattern matching.
    for role in content_roles:
        checker = CONTENT_CHECKERS[role]
        best_index, best_rate = None, 0.0

        for idx, values in columns_by_index.items():
            if idx in claimed:
                continue
            rate = _content_match_rate(values, checker)
            if rate > best_rate:
                best_index, best_rate = idx, rate

        if best_index is not None and best_rate >= CONTENT_MATCH_THRESHOLD:
            field_indices[role] = best_index
            claimed[best_index] = role
            confidence[role] = {
                "method": "content",
                "column_index": best_index,
                "match_rate": round(best_rate, 3),
            }
        else:
            confidence[role] = {"method": "unresolved", "best_rate_seen": round(best_rate, 3)}

    # Pass 2: header name matching, over whatever's left. Exact match first
    # (the strongest remaining signal), substring fallback second -- doing
    # it in that order is what stops a short synonym like "ip" from
    # matching inside an unrelated header like "shipping_method" before
    # the real, exact "ip" column ever gets a chance to be checked.
    #
    # Content roles that Pass 1 couldn't resolve join this exact-match pass
    # too (never the substring one): a sparse column -- e.g. phone filled
    # in only 10 of the sampled rows, below MIN_SAMPLE_SIZE -- gives content
    # matching too little to go on, but a column literally headed "phone"
    # is still the phone column. Fields are optional; sparse is normal.
    unresolved_content_roles = [r for r in content_roles if r not in field_indices]
    for role in header_only_roles + unresolved_content_roles:
        for idx, raw_header in enumerate(header):
            if idx in claimed:
                continue
            if _normalize_header(raw_header) in _exact_header_names(role):
                field_indices[role] = idx
                claimed[idx] = role
                confidence[role] = {
                    "method": "header_exact",
                    "column_index": idx,
                    "header_text": raw_header,
                }
                break

    # Pass 2b: a single combined-name column, only when the file has no
    # dedicated first/last-name column. Must run BEFORE the substring
    # fallback: there, a header of just "name" matches firstname (because
    # "name" is a substring of "firstname"), which put the whole full name
    # into firstname and left lastname empty.
    name_roles = [r for r in ("firstname", "lastname") if r in header_only_roles]
    if name_roles and not any(r in field_indices for r in name_roles):
        for idx, raw_header in enumerate(header):
            if idx not in claimed and _normalize_header(raw_header) in {_normalize_header(h) for h in FULL_NAME_HEADERS}:
                field_indices["name"] = idx
                claimed[idx] = "name"
                confidence["name"] = {"method": "header_exact", "column_index": idx, "header_text": raw_header}
                for role in name_roles:
                    confidence[role] = {"method": "split_from_name", "column_index": idx}
                break

    for role in header_only_roles:
        if role in field_indices or ("name" in field_indices and role in name_roles):
            continue
        for idx, raw_header in enumerate(header):
            if idx in claimed:
                continue
            if _header_matches(raw_header, role):
                field_indices[role] = idx
                claimed[idx] = role
                confidence[role] = {
                    "method": "header_substring",
                    "column_index": idx,
                    "header_text": raw_header,
                }
                break
        else:
            confidence[role] = {"method": "unresolved"}

    schema = DatasetSchema(header=tuple(roles), field_indices=field_indices, has_header=True)
    return schema, confidence
