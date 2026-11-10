"""
Runs the full pipeline (rules/disposition.py) against a CSV and writes the
three output artifacts described in scoremark_project.md: a report, a clean
file, and a garbage file. This is the same pipeline Phase 6's Flask routes
will call later -- building it as a standalone CLI first means it can be
verified (and manually inspected) before any UI exists to hide behind.

Usage:
    python analyze.py samples/messy_sample.csv
    python analyze.py samples/clean_sample.csv

Writes clean.csv, garbage.csv, and report.json into output/<input stem>/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rules.disposition import run_pipeline
from rules.io import CsvStructureError, read_csv_rows

# The declared schema for both sample files -- see scoremark_project.md's
# "Schema Resolution" section: canned samples get an explicit schema because
# we wrote them and can be precise, rather than relying on inference.
SAMPLE_SCHEMA = {
    "customer_id": "text",  # an opaque identifier, not a format worth validating
    "full_name": "name",
    "email": "email",
    "phone": "phone",
    "signup_date": "date",
    "zip_code": "integer_code",
}
SAMPLE_KEY_COLUMNS = ["email"]

#: analyze.py only forces the declared sample schema for files we actually
#: wrote ourselves. Any other file -- like a real-world export someone
#: hands us -- goes through full inference instead, exactly as
#: scoremark_project.md's "Schema Resolution" section describes. Applying
#: our own sample schema (and, worse, our own hardcoded uniqueness key) to
#: a file with completely different columns produces meaningless results,
#: not an error -- which is a more dangerous failure mode, not a safer one.
KNOWN_SAMPLE_FILES = {"clean_sample.csv", "messy_sample.csv"}


def main() -> None:
    input_path = Path(sys.argv[1] if len(sys.argv) > 1 else "samples/messy_sample.csv")

    try:
        # Same reader as the web app: any encoding, malformed rows set aside.
        read = read_csv_rows(input_path)
        df = read.dataframe
    except CsvStructureError as error:
        print(f"Could not process {input_path}:")
        print(f"  {error}")
        sys.exit(1)

    if input_path.name in KNOWN_SAMPLE_FILES:
        declared_schema, key_columns = SAMPLE_SCHEMA, SAMPLE_KEY_COLUMNS
        print(f"Using the declared Scoremark sample schema (recognized filename: {input_path.name}).")
    else:
        declared_schema, key_columns = None, None
        print("Unrecognized filename -- inferring the schema and key column from the data itself.")

    result = run_pipeline(df, declared_schema=declared_schema, key_columns=key_columns,
                          malformed_rows=read.malformed_rows)
    if read.malformed_rows:
        print(f"{len(read.malformed_rows)} malformed row(s) set aside into garbage.csv "
              f"(first at line {read.malformed_rows[0].line_number}).")

    output_dir = Path("output") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    result["clean_df"].to_csv(output_dir / "clean.csv", index=False)
    result["garbage_df"].to_csv(output_dir / "garbage.csv", index=False)
    (output_dir / "report.json").write_text(json.dumps(result["report"], indent=2, default=str))

    print(f"Input:   {input_path} ({len(df)} rows)")
    print(f"Clean:   {output_dir / 'clean.csv'} ({len(result['clean_df'])} rows)")
    print(f"Garbage: {output_dir / 'garbage.csv'} ({len(result['garbage_df'])} rows)")
    print(f"Report:  {output_dir / 'report.json'}")
    print()
    print("Report summary:")
    print(json.dumps(result["report"], indent=2, default=str))


if __name__ == "__main__":
    main()
