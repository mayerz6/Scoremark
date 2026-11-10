"""
Server-side upload guards for the public /analyze endpoint -- SCORE-5.

Client-side JS (SCORE-7, not built yet) can warn a visitor about an
oversized file before they even submit, but it is never the real
enforcement: it's trivially bypassed (disabled JS, a raw request to the
endpoint). Every check here runs again, unconditionally, on the server --
that's the only place "no" can actually be made to stick.

These guards only ever apply to the real-upload path. The two canned
samples (scoremark_project.md's Input section) are bundled, zero-risk
files that never touch attacker-controlled bytes, so they skip all of
this by design -- see app.py's analyze() for where that branch happens.
"""

from __future__ import annotations

#: 2 MB / 20,000 rows / 50 columns -- the exact caps documented in
#: scoremark_project.md's Input section. Not arbitrary: chosen there so a
#: strict file-shape limit always finishes processing in well under a
#: second, regardless of what's actually inside the file.
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 20_000
MAX_COLUMNS = 50
ALLOWED_EXTENSION = ".csv"

#: Flask's own MAX_CONTENT_LENGTH, set slightly above MAX_FILE_SIZE_BYTES
#: to allow for multipart boundary/header overhead around the file's own
#: bytes -- the exact per-file cap below is still enforced at exactly
#: MAX_FILE_SIZE_BYTES; this is just the outer net so a legitimate
#: near-2MB file isn't rejected for reasons that have nothing to do with
#: the file itself.
FLASK_MAX_CONTENT_LENGTH = MAX_FILE_SIZE_BYTES + 64 * 1024


class UploadRejected(ValueError):
    """
    Raised with a message that's always safe to show directly to the
    visitor -- every raise site in this module writes the message with
    that in mind, the same "clear, specific, never a stack trace"
    principle CsvStructureError (rules/io.py) already follows.
    """


def validate_filename(filename: str) -> None:
    if not filename or "." not in filename:
        raise UploadRejected("The uploaded file needs a name ending in .csv.")
    if not filename.lower().endswith(ALLOWED_EXTENSION):
        raise UploadRejected("Only .csv files are accepted.")


def validate_file_size(size_in_bytes: int) -> None:
    if size_in_bytes == 0:
        raise UploadRejected("The uploaded file is empty.")
    if size_in_bytes > MAX_FILE_SIZE_BYTES:
        raise UploadRejected(
            f"File is too large ({size_in_bytes / 1024 / 1024:.2f} MB). "
            f"Maximum allowed is {MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f} MB."
        )


def validate_is_text_content(content: bytes | str) -> None:
    """
    A cheap, well-known signal that a file isn't really text: genuine
    text/CSV content essentially never contains a null character; binary
    files (a renamed image, a Word doc, etc.) very often do within their
    first few KB. This is the "content, not just the .csv extension"
    half of the check -- extension alone is a label, never trusted alone
    anywhere else in this project either (see rules/io.py's delimiter
    detection for the same principle applied to a different label).

    app.py passes the DECODED text (rules/io.decode_csv_bytes()): raw
    UTF-16 bytes are full of 0x00 bytes -- "a" is 61 00 -- so checking raw
    bytes rejected every UTF-16 export as binary. Decoded, real UTF-16 text
    has no null characters; a binary file decoded as Latin-1 still does.
    """
    null = "\x00" if isinstance(content, str) else b"\x00"
    if null in content[:8192]:
        raise UploadRejected("This doesn't look like a text CSV file (binary content detected).")


def validate_dataframe_shape(row_count: int, column_count: int) -> None:
    if row_count > MAX_ROWS:
        raise UploadRejected(f"File has {row_count:,} rows; maximum allowed is {MAX_ROWS:,}.")
    if column_count > MAX_COLUMNS:
        raise UploadRejected(f"File has {column_count} columns; maximum allowed is {MAX_COLUMNS}.")
