"""
The one sanctioned way to read a CSV anywhere in this project.

pandas.read_csv() has two defaults that would silently break everything
else in this package if used directly:

  1. It auto-converts strings like "NULL", "N/A", "n/a", "NaN" into real
     NaN during parsing (its built-in na_values list), which destroys the
     empty-vs-sentinel distinction schema.missing_kind() depends on before
     our own code ever sees the data.
  2. It infers numeric/date dtypes automatically, which breaks every
     value-pattern checker in schema.py -- they match against plain
     strings, not floats or Timestamps.

So rows are parsed with the standard library's csv module and every value
stays exactly the text that was in the file. Reading everything as text
and letting schema.py decide what a value "really" is afterward is the
whole point of this project.

It also handles what real-world files do that the original samples never
exercised:

  - Encodings other than UTF-8 -- UTF-16 (Excel's "Unicode Text" and many
    database exports), UTF-8 with a byte-order mark, Windows-1252. See
    decode_csv_bytes().
  - Delimiters other than a comma (semicolon, pipe, tab) -- detected with
    csv.Sniffer rather than a hand-rolled frequency count.
  - Malformed rows -- more fields than the header, usually an unescaped
    delimiter inside an unquoted value ("Alamo, Kamal"). One such row used
    to reject the entire file. Now the row is set aside, unscored, with
    its line number and raw text (see read_csv_rows()), and every
    well-formed row is still analyzed. Splitting it back into columns
    would mean guessing which comma was the stray one -- not something
    this project does.
"""

from __future__ import annotations

import codecs
import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

#: Delimiters worth sniffing for. Order doesn't matter -- csv.Sniffer
#: decides based on which one appears with consistent frequency per line.
_CANDIDATE_DELIMITERS = ",;|\t"

#: How much of the file to sample when sniffing -- large enough to span
#: several real rows, small enough to stay cheap even on a multi-MB file.
_SNIFF_SAMPLE_BYTES = 8192

#: Byte-order marks, checked longest-first. A BOM is the file stating its
#: own encoding outright -- stronger evidence than any guess.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


class CsvStructureError(ValueError):
    """Raised when a file can't be parsed as a delimited table at all."""


@dataclass
class MalformedRow:
    row_number: int  # 0-based position among data rows -- same numbering as original_row_number
    line_number: int  # 1-based physical line in the file (the header is line 1)
    expected_fields: int
    found_fields: int
    raw: str


@dataclass
class CsvReadResult:
    dataframe: pd.DataFrame
    malformed_rows: list[MalformedRow] = field(default_factory=list)
    delimiter: str = ","
    encoding: str = "utf-8"

    @property
    def total_rows(self) -> int:
        return len(self.dataframe) + len(self.malformed_rows)


def decode_csv_bytes(raw: bytes) -> tuple[str, str]:
    """
    Returns (text, encoding_used). Tries, in order: a byte-order mark,
    strict UTF-8, Windows-1252, then Latin-1 (which can decode any byte, so
    this never fails -- whether the result is really text is
    upload_guards.validate_is_text_content()'s call, made on the decoded
    text, where a UTF-16 file no longer looks like "binary").
    """
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                break
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise AssertionError("unreachable: latin-1 decodes any byte sequence")


def detect_delimiter(path_or_buffer) -> str:
    """
    Sniffs the delimiter from a sample of the file using the standard
    library's csv.Sniffer. Falls back to comma if nothing is confidently
    detected (e.g. a single-column file with no delimiter at all).
    """
    return _sniff(_read_sample(path_or_buffer))


def _sniff(sample: str) -> str:
    # Whole lines only: a row cut off mid-way can have a different
    # delimiter count than the rest and throw the sniffer off.
    if "\n" in sample:
        sample = sample[: sample.rfind("\n")]
    try:
        return csv.Sniffer().sniff(sample, delimiters=_CANDIDATE_DELIMITERS).delimiter
    except csv.Error:
        return ","


def _read_sample(path_or_buffer) -> str:
    if hasattr(path_or_buffer, "read"):
        position = path_or_buffer.tell() if hasattr(path_or_buffer, "tell") else None
        raw = path_or_buffer.read(_SNIFF_SAMPLE_BYTES)
        if position is not None:
            path_or_buffer.seek(position)
        return decode_csv_bytes(raw)[0] if isinstance(raw, bytes) else raw

    with open(path_or_buffer, "rb") as f:
        return decode_csv_bytes(f.read(_SNIFF_SAMPLE_BYTES))[0]


def _load_text(path_or_buffer) -> tuple[str, str]:
    if hasattr(path_or_buffer, "read"):
        content = path_or_buffer.read()
        return decode_csv_bytes(content) if isinstance(content, bytes) else (content, "text")
    return decode_csv_bytes(Path(path_or_buffer).read_bytes())


def _unique_headers(header: list[str]) -> list[str]:
    """pandas' own rules: blank -> "Unnamed: <i>", repeats -> "name.1", "name.2"."""
    used: set[str] = set()
    result = []
    for i, name in enumerate(header):
        base = name if name.strip() else f"Unnamed: {i}"
        candidate, n = base, 0
        while candidate in used:
            n += 1
            candidate = f"{base}.{n}"
        used.add(candidate)
        result.append(candidate)
    return result


def read_csv_rows(path_or_buffer, delimiter: str | None = None, source_name: str | None = None) -> CsvReadResult:
    """
    Reads any supported CSV into an all-text DataFrame, setting aside rows
    with MORE fields than the header as MalformedRow records instead of
    failing the whole file.

    - A row with FEWER fields is padded with "" (pandas' behavior too):
      trailing empty columns are routinely omitted by exporters, and the
      missing cells then count as empty for Completeness -- nothing guessed.
    - Extra fields that are all empty (a trailing delimiter) carry no data
      and are dropped rather than flagging the row.
    - The DataFrame's index is each row's original 0-based data-row
      position, so numbering in the garbage file still points at the right
      row even when malformed rows are set aside before it.

    delimiter: pass one explicitly to skip sniffing.
    source_name: the name to use in error messages (e.g. the uploaded
    filename); defaults to the path's file name.
    """
    if source_name:
        name = source_name
    elif hasattr(path_or_buffer, "read"):
        # An in-memory upload has no name -- never show its Python repr.
        name = Path(str(getattr(path_or_buffer, "name", "") or "")).name or "the uploaded file"
    else:
        name = Path(path_or_buffer).name

    text, encoding = _load_text(path_or_buffer)
    if delimiter is None:
        delimiter = _sniff(text[:_SNIFF_SAMPLE_BYTES])

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next((row for row in reader if row), None)
        if header is None or not any(cell.strip() for cell in header):
            raise CsvStructureError(f"'{name}' has no header row -- the file is empty or contains only blank lines.")
        header = _unique_headers(header)
        width = len(header)

        rows, index, malformed = [], [], []
        position = 0
        for row in reader:
            if not row:  # a truly blank line, as pandas' skip_blank_lines
                continue
            if len(row) > width and not any(cell.strip() for cell in row[width:]):
                row = row[:width]
            if len(row) > width:
                malformed.append(MalformedRow(
                    row_number=position,
                    line_number=reader.line_num,
                    expected_fields=width,
                    found_fields=len(row),
                    raw=delimiter.join(row),
                ))
            else:
                rows.append(row + [""] * (width - len(row)))
                index.append(position)
            position += 1
    except csv.Error as error:
        raise CsvStructureError(
            f"'{name}' could not be read as a '{delimiter}'-delimited file "
            f"(line {reader.line_num}): {error}."
        ) from error

    dataframe = pd.DataFrame(rows, columns=header, index=index, dtype=object)
    return CsvReadResult(dataframe=dataframe, malformed_rows=malformed, delimiter=delimiter, encoding=encoding)


def read_csv_as_text(path_or_buffer, delimiter: str | None = None, source_name: str | None = None) -> pd.DataFrame:
    """
    Strict variant of read_csv_rows(): any malformed row raises
    CsvStructureError. For callers that need an all-or-nothing table; the
    web app and analyze.py use read_csv_rows() and report malformed rows
    instead.
    """
    result = read_csv_rows(path_or_buffer, delimiter=delimiter, source_name=source_name)
    if result.malformed_rows:
        first = result.malformed_rows[0]
        name = source_name or (Path(path_or_buffer).name if not hasattr(path_or_buffer, "read") else "the file")
        raise CsvStructureError(
            f"'{name}' has {len(result.malformed_rows)} row(s) with more fields than the header "
            f"-- first at line {first.line_number} ({first.found_fields} fields, expected "
            f"{first.expected_fields}). This usually means an unescaped delimiter inside a value "
            "that was never wrapped in quotes."
        )
    return result.dataframe
