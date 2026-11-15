"""
Generates samples/clean_sample.csv and samples/messy_sample.csv.

clean_sample.csv: CLEAN_ROW_COUNT synthetic customer records, each complete,
valid, unique, and already consistently formatted. Running Scoremark against
it should report zero problems of every kind -- this is what proves the tool
doesn't invent issues where none exist. A handful of ZIP codes are forced to
have leading zeros (e.g. "02134") on purpose, so the demo visibly exercises
the leading-zero guard in rules/schema.py even on data with no real quality
problems -- a leading-zero ZIP is not a quality issue, just a classification
one.

messy_sample.csv: the exact same rows, with a known, printed, non-overlapping
count of each problem type injected -- see INJECTED_COUNTS below. This is the
file the README's falsifiable claim is built on: "injected N of each problem,
Scoremark's report found exactly N of each."

Run with: python samples/generate_samples.py
Writes clean_sample.csv, messy_sample.csv, and injected_counts.json, all in
this same samples/ directory. Deterministic (fixed seed) -- running it again
produces byte-identical output.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from faker import Faker

SEED = 42
CLEAN_ROW_COUNT = 60
LEADING_ZERO_ZIP_ROW_COUNT = 4

# Counts of each problem injected into messy_sample.csv, chosen from
# disjoint rows so every count is independently attributable -- no row
# carries more than one injected problem, and the duplicated rows are never
# also one of the missing/invalid/inconsistent rows.
INJECTED_COUNTS = {
    "missing_phone_rows": 4,
    "invalid_email_rows": 4,
    "inconsistent_name_rows": 4,
    "duplicated_rows": 5,
}

SAMPLES_DIR = Path(__file__).parent
COLUMNS = ["customer_id", "full_name", "email", "phone", "signup_date", "zip_code"]


def generate_clean_rows(count: int) -> list[dict]:
    fake = Faker()
    fake.seed_instance(SEED)

    rows = []
    used_emails: set[str] = set()

    for i in range(count):
        first = fake.first_name()
        last = fake.last_name()
        full_name = f"{first} {last}"

        base_email = f"{first}.{last}".lower() + "@example.com"
        email = base_email
        suffix = 2
        while email in used_emails:
            email = f"{first}.{last}{suffix}".lower() + "@example.com"
            suffix += 1
        used_emails.add(email)

        zip_code = fake.numerify("#####")
        if i < LEADING_ZERO_ZIP_ROW_COUNT:
            # Force a leading zero so this case is guaranteed to appear,
            # rather than left to chance -- see module docstring.
            zip_code = "0" + zip_code[1:]

        rows.append({
            "customer_id": f"CUST-{1000 + i}",
            "full_name": full_name,
            "email": email,
            "phone": fake.numerify("###-###-####"),
            "signup_date": fake.date_between(start_date="-3y", end_date="today").strftime("%m/%d/%Y"),
            "zip_code": zip_code,
        })

    return rows


def inject_problems(clean_rows: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    indices = list(range(len(clean_rows)))
    rng.shuffle(indices)

    missing_count = INJECTED_COUNTS["missing_phone_rows"]
    invalid_count = INJECTED_COUNTS["invalid_email_rows"]
    inconsistent_count = INJECTED_COUNTS["inconsistent_name_rows"]
    duplicate_count = INJECTED_COUNTS["duplicated_rows"]

    missing_rows = indices[:missing_count]
    invalid_rows = indices[missing_count:missing_count + invalid_count]
    inconsistent_rows = indices[
        missing_count + invalid_count:missing_count + invalid_count + inconsistent_count
    ]
    duplicate_source_rows = indices[
        missing_count + invalid_count + inconsistent_count:
        missing_count + invalid_count + inconsistent_count + duplicate_count
    ]

    messy_rows = [dict(row) for row in clean_rows]

    for i in missing_rows:
        messy_rows[i]["phone"] = ""

    for i, row_index in enumerate(invalid_rows):
        # Distinct malformed values per row -- a repeated literal like
        # "not-an-email" on every row would make those rows duplicates of
        # each other under the email key, which would inflate the
        # Uniqueness count for a reason that has nothing to do with the
        # duplicate-row injection below. Each one must fail the email
        # pattern differently, and differently from every other row.
        messy_rows[row_index]["email"] = f"not-an-email-{i + 1}"

    for i in inconsistent_rows:
        # Still the right person, still a real name -- just inconsistently
        # cased, which Consistency should auto-fix rather than reject.
        messy_rows[i]["full_name"] = messy_rows[i]["full_name"].lower()

    for i in duplicate_source_rows:
        messy_rows.append(dict(clean_rows[i]))  # verbatim duplicate, appended at the end

    return messy_rows


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    clean_rows = generate_clean_rows(CLEAN_ROW_COUNT)
    messy_rows = inject_problems(clean_rows)

    write_csv(SAMPLES_DIR / "clean_sample.csv", clean_rows)
    write_csv(SAMPLES_DIR / "messy_sample.csv", messy_rows)

    summary = {
        **INJECTED_COUNTS,
        "clean_sample_row_count": len(clean_rows),
        "messy_sample_row_count": len(messy_rows),
        "leading_zero_zip_rows": LEADING_ZERO_ZIP_ROW_COUNT,
        "seed": SEED,
    }
    (SAMPLES_DIR / "injected_counts.json").write_text(json.dumps(summary, indent=2))

    print("Generated clean_sample.csv:", len(clean_rows), "rows")
    print("Generated messy_sample.csv:", len(messy_rows), "rows")
    print("Injected problems:", json.dumps(INJECTED_COUNTS, indent=2))
    print("Ground truth written to injected_counts.json")


if __name__ == "__main__":
    main()
