import csv

import chardet

#: Delimiters worth sniffing for -- same set as rules/io.py in the web tool.
_CANDIDATE_DELIMITERS = ",;|\t"
_SNIFF_SAMPLE_CHARS = 8192


def detect_encoding(file_path):

    with open(file_path, "rb") as f:

        raw_data = f.read(50000)

    result = chardet.detect(raw_data)
    encoding = result["encoding"]

    # chardet only sees the first 50 KB: "ascii" there doesn't rule out a
    # non-ASCII character later in the file, and UTF-8 reads every ASCII
    # file identically -- so use the superset. None (e.g. an empty file)
    # falls back to UTF-8 too, rather than the OS locale's default.
    if encoding is None or encoding.lower() == "ascii":
        return "utf-8"
    return encoding


def detect_delimiter(file_path, encoding):
    """
    Sniffs the delimiter from the start of the file with the standard
    library's csv.Sniffer. Falls back to comma if nothing is confidently
    detected (e.g. a single-column file).
    """
    with open(file_path, encoding=encoding, newline="") as f:
        sample = f.read(_SNIFF_SAMPLE_CHARS)

    # Only whole lines: a row cut off mid-way can have a different
    # delimiter count than the rest and throw the sniffer off.
    if "\n" in sample:
        sample = sample[: sample.rfind("\n")]

    try:
        return csv.Sniffer().sniff(sample, delimiters=_CANDIDATE_DELIMITERS).delimiter
    except csv.Error:
        return ","
