# Scoremark — Data Quality Benchmark & Cleansing Tool

## Objective

Scoremark takes a tabular dataset (a canned sample, or a visitor's own small CSV) and runs it through four precisely-defined data quality rules — Completeness, Validity, Uniqueness, Consistency. It reports a score for each rule, and goes one step further than a report: it splits the input into a **clean file** (rows that pass, with safe formatting fixes applied) and a **garbage file** (rows that failed, with the exact reason recorded), so the output is something a reviewer can verify directly rather than take on faith.

This is a productized version of real experience, not an invented exercise: it generalizes the Python data-cleaning/validation work already on the resume (`Career_Projects.md` → "Python Data Cleaning & Validation Toolkit") into something interactive and inspectable.

**What this is not:** a compliance product, an enterprise data governance platform, or a tool for sensitive/confidential data. It's a focused demonstration of data quality engineering, built and tested on public/synthetic data only. See "Explicitly Out of Scope" below.

## Pipeline Overview

```
input (canned sample OR uploaded CSV)
    -> resolve schema (declared, for samples | inferred, for uploads)
    -> apply safe Consistency fixes (trim, Title Case, lowercase email, canonical date format)
    -> score Completeness, Validity, Consistency per column (post-fix)
    -> score Uniqueness across the whole dataset (post-fix)
    -> route every row to clean.csv or garbage.csv
    -> render the four-rule report + both files for download
```

## Input

- **Canned samples** (primary, zero-risk path): two bundled files, `clean_sample.csv` and `messy_sample.csv`, selected by the visitor with a button, never uploaded over the network.
- **Real upload** (secondary, guarded path): CSV only for v1. Hard limits: **2 MB max file size, 20,000 rows max, 50 columns max**, rejected with a clear message before any processing if exceeded. Extension *and* content-sniffed MIME type must both say CSV — extension alone is not trusted. Files are processed directly from the upload stream into memory; nothing is written to disk.
- Basic per-IP rate limiting on the upload endpoint (not on the canned-sample endpoint, which carries no risk).

## Schema Resolution

Every rule needs to know, per column, what type/format is expected. There are two ways Scoremark gets that:

**Declared (canned samples):** a hardcoded schema dict (`{"email": "email", "zip_code": "integer_code", ...}`), since we control these files and can be precise on purpose — this is also what makes the samples useful as a worked example in the README.

**Inferred (uploads):** statistical type inference, run once per column before scoring begins.

1. For each column, test every non-null value against a fixed, ordered list of type checkers, most specific first: `email → phone → date → boolean → integer → float → text (fallback, always matches)`.
2. For each checker, compute its match rate (fraction of non-null values it accepts).
3. Walk the checkers in that specificity order; the **first** one whose match rate is **≥ 90%** becomes the column's inferred type. If none clears 90%, the column is `unclassified` — Validity is not scored for it, and it's reported as low-confidence rather than guessed.
4. **Minimum sample size:** a column needs at least 20 non-null values before any type is trusted; below that, it's `insufficient_data`, not guessed from a handful of values.
5. **Leading-zero guard:** before trusting an `integer` classification, verify the round-trip `str(int(v)) == v` holds for the sampled values. If it doesn't (e.g. ZIP codes, account numbers with leading zeros), the column is classified `integer_code` instead — a string-typed identifier, not a number — and is never cast to int anywhere in the pipeline.

The winning checker *is* that column's Validity rule going forward — same function, used both to classify the column and to flag individual bad values in it.

## The Four Rules

### Completeness
**Measures:** the missing-value rate per column. A value is "missing" if it's truly empty, **or** if it's a recognized null-sentinel string (`NULL`, `N/A`, `n/a`, `none`, `-`, case-insensitive) — a sentinel masquerading as data is still an absence of real data.
**Granularity:** per column.
**Default policy for uploads (no declared required/optional distinction available):** every column is treated as required.
**Output:**
```json
{ "column": "email", "missing_count": 12, "total_rows": 500, "missing_pct": 2.4 }
```

### Validity
**Measures:** type/format conformance per column, against the declared or inferred type. A null-sentinel value (see Completeness) *also* counts here as an invalid representation — it's missing a real value **and** the way it's missing is non-standard, and both facts matter independently.
**Granularity:** per column.
**Output:**
```json
{ "column": "age", "type": "integer", "confidence": 0.97, "invalid_count": 8, "invalid_pct": 1.6, "examples": ["twelve", "N/A", "-3?"] }
```
For `unclassified`/`insufficient_data` columns: `invalid_count` is `null` and a note explains why validity wasn't scored.
**File-level check, not per-column:** the raw upload is decoded as UTF-8 once, up front. A decode failure is reported as a single top-level warning ("file encoding issue, N bytes could not be decoded"), not folded into any one column's stats — encoding is a property of the whole file, not of a row.

### Uniqueness
**Measures:** duplicate rows, by a declared key (canned samples) or an inferred key (an `email`/`integer_code`-type column with a near-100% uniqueness rate on the clean sample is assumed to be the key; if no such column exists, falls back to whole-row duplication).
**Granularity:** whole dataset.
**Duplicate policy:** the **first** occurrence (in original row order) of each key is kept; every later occurrence of the same key is a duplicate.
**Output:**
```json
{ "key_columns": ["email"], "key_source": "declared", "duplicate_group_count": 5, "duplicate_row_count": 7 }
```

### Consistency
**Measures:** rows whose formatting was normalized — Title Case for name columns (`larry mayers` → `Larry Mayers`), lowercase for email columns, a single canonical date format (`MM/DD/YYYY`) for date columns recognized under any parseable format. This is a count of **what was auto-corrected**, not a pass/fail.
**Granularity:** per column.
**Output:**
```json
{ "column": "full_name", "rule": "title_case", "autocorrected_count": 34, "autocorrected_pct": 6.8 }
```

## Row Disposition: Clean vs. Garbage

Applied in this order, per row, after schema resolution:

1. Apply the Consistency fixes above (trim, Title Case, lowercase email, canonical date format). These never disqualify a row — they only change its representation.
2. Check Completeness and Validity on the now-fixed row.
3. Check Uniqueness against every other row (first occurrence of a key wins).
4. **Any row that fails step 2, or is a non-first occurrence of a duplicate key → `garbage.csv`**, with two added columns: `original_row_number` (traceable back to the source file) and `failure_reasons` (semicolon-joined, e.g. `missing:phone; duplicate_of_row:12`).
5. **Every other row → `clean.csv`**, in its fixed form, with one added column: **`was_autocorrected`** (`true`/`false`) — so nothing the tool silently changed is actually hidden from whoever reads the output.

Nothing is ever invented. A missing value, an invalid value, or a duplicate is never guessed or filled in — only representation (case, whitespace, date format) is touched, and only when the fix doesn't change what the value means.

## Output Artifacts (per run)

- The four-rule report (JSON, rendered as stat cards + Chart.js charts on the page).
- `clean.csv` — download link.
- `garbage.csv` — download link.

## Sample Datasets (built in Phase 3)

Proposed shared schema for both samples — a small synthetic customer directory: `customer_id, full_name, email, phone, signup_date, zip_code`. `zip_code` is deliberately included to demonstrate the leading-zero guard in Schema Resolution (several codes like `02134` so the inference step must classify the column as `integer_code`, not `integer`, to avoid corrupting them).

- `clean_sample.csv` — every row valid, complete, unique, and already consistently formatted. Confirms Scoremark doesn't invent problems where none exist.
- `messy_sample.csv` — the same shape, with a **known, exact** number of each problem type injected by `generate_samples.py` (duplicate rows, missing required fields, invalid emails/phone formats, inconsistent name casing and date formats). The generator prints the exact counts it injected, so the README can state a falsifiable claim: "injected N duplicates, M missing fields, P invalid values — Scoremark's report found exactly N, M, P." Precise counts are decided when the generator is written, not guessed now.

## Explicitly Out of Scope for v1

- No compliance claims of any kind — this is inspired by data quality practices used in regulated industries, it is not an audited compliance tool.
- No file formats besides CSV.
- No persistence of uploaded files beyond the request that processes them.
- No auto-fixing of anything beyond representation (case, whitespace, date format) — never a guessed/invented value.
- No authentication, no saved history between runs.

## Tech Stack & Hosting (recap)

Python + Flask + pandas for the backend; Chart.js (CDN) for client-side chart rendering, no server-side image generation. Deployed to PythonAnywhere's free tier (always-on, no cold-start, browser-based setup — see prior discussion for why this was chosen over Render for this specific use case). Repo: `mayerz6/scoremark`, same ownership convention as Cartana, kept outside the portfolio's own git history.
