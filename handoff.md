# Scoremark ETL Tool — Handoff

Last updated: 2026-11-07

## What this document is

A record of the actual trial-and-error that got the fixed-schema ETL tool
(`main.py`, `etl/`) from "crashes on startup" to "runs cleanly end to end
and is now matched by a content-detecting hybrid version that produces
byte-identical output." Written so the next person picking this up — or
future me — doesn't have to re-derive any of this from scratch, and so the
GitHub README for this project can point here for the real engineering
story instead of just the finished code.

For how each tool actually works once it's running, see:
- `docs/FIXED_SCHEMA_ETL_TUTORIAL.md` — the hand-mapped batch pipeline
- `etl/schema_detection.py`'s module docstring — the hybrid detector

## The dataset that found all of this

`datasets/samples/records/messy_sample_4.csv` — a real 19.6MB, ~38,796-row,
34-column e-commerce order export, semicolon-delimited, UTF-8, containing
genuine Cyrillic customer names and some pre-existing (upstream, not ours
to fix) `?????` mojibake where text was already lost before this file was
created. Nothing about this file was synthetic or simplified for testing —
every bug below was found because this file is exactly as messy as a real
export actually is.

## The bugs, in the order they were found

### 1. Comma delimiter on a semicolon-delimited file

**Symptom:** `pandas.errors.ParserError: Expected 9 fields in line 1757, saw 10`
(in the separate `rules/` tool, which hit this file first) and, in this
tool, rows being silently dropped by `CSVExtractor`'s `len(row) <
required_min_columns` check before ever reaching the transformer.

**Cause:** the file is semicolon-delimited; the code assumed comma.

**Fix:** pass the real delimiter (`;`) explicitly.

**Lesson:** never hardcode a delimiter for a file you haven't inspected.
(The `rules/` tool's answer to this — `csv.Sniffer`-based auto-detection —
was considered for this tool too; see "What wasn't ported over," below,
for why it wasn't.)

### 2. `if valid: self.loader.load(valid)` — a missing file three steps downstream of its real cause

**Symptom:** `FileNotFoundError` on `processed_dataset.csv`, raised by
*stage 2*, trying to read a file *stage 1* was supposed to have written.

**Cause:** `Pipeline.run()` only wrote the clean output file if at least
one row survived. When every row failed (because of bug #3, below), the
file was never created at all — not written-empty, not written with just
a header, simply never touched.

**Fix:** always call `self.loader.load(valid)` (it writes a header-only
file correctly if `valid` is empty), and print an explicit warning when
that happens, so a future all-garbage run fails loudly with a clear
message instead of a missing file somewhere else in the pipeline.

**Lesson:** a pipeline stage that can legitimately produce zero output
rows needs to say so explicitly. A silently-missing file and a
deliberately-empty file look identical to whatever reads them next, and
only one of those is actually fine.

### 3. `schema` and `final_schema` swapped between the two stages — the real reason every row failed

**Symptom:** `Valid rows: 0` out of ~38,796, even after fixing the
delimiter.

**Cause:** `datasets/samples/order_dataset.py`'s `schema` has the real
column positions in the raw 34-column file (`firstname` at index 7,
`email` at index 9, ...). `datasets/samples/confirmed_dataset_headers.py`'s
`final_schema` has simple sequential indices (0-7), correct only for the
*already-reduced* 8-column file stage 1 produces. Stage 1 was using
`final_schema` against the raw file — so `email` was being read from
column 2, which is actually the invoice number. Every row then failed
`EmailValidationRule` for a reason that had nothing to do with the
customer's actual email.

**Fix:** stage 1 uses `schema`; stage 2 uses `final_schema`.

**Lesson, and the single most important one from this whole file:**
position-based field access (`raw_record[idx]`) has no way to notice it's
reading the wrong thing. `row["email"]` would have raised `KeyError`
immediately if the mapping were wrong; `row[2]` just returns whatever's
there and calls it an email. The mistake didn't surface as "wrong column,"
it surfaced as "100% of rows mysteriously fail validation" — three layers
and (at the time) an unknown number of debugging steps away from its
actual cause. This is the precise trade-off discussed when deciding to
build the hybrid detector: automatic detection isn't just a convenience,
it's a way of never hand-authoring the one line in this whole tool that's
most capable of failing silently.

### 4. `latin-1` on a UTF-8 file

**Symptom:** garbled text in `firstname` (`'�\x90лек�\x81анд�\x80'`), not
an exception — `latin-1` can decode any byte sequence, so it never fails,
it just produces nonsense silently.

**Cause:** `CSVExtractor` was constructed with `encoding="latin-1"`.

**Fix verified empirically, not assumed:** decoded the entire raw file
strictly as both candidates —

```python
raw.decode('utf-8')         # succeeds, zero errors, whole file
raw.decode('windows-1251')  # fails partway: byte 0x98 at position 19537
```

UTF-8 is correct. Changed both `CSVExtractor` calls (stage 1 reading the
raw file, stage 2 reading stage 1's own output) to `encoding="utf-8"`.

**Lesson:** `latin-1` deserves special suspicion specifically *because* it
never raises `UnicodeDecodeError` on any input. A codec that can't fail is
a codec that can't tell you when it's wrong.

### 5. A leftover debug print, and a missing dependency, both blocking the same run

- `ModuleNotFoundError: No module named 'chardet'` — `etl/utils/encoding.py`
  imports it at module level, so just importing `csv_extractor.py` failed
  before `main.py` could run at all, even though (see "Known gaps" below)
  nothing in the current code path actually calls the function that needs
  it. Fixed by installing it; the deeper issue (an unused capability that
  can still break startup) is still open.
- `print("RAW ROW:", raw[:15])` in `Pipeline.run()`, referencing the loop
  variable after the loop — once bugs #3 and #4 were fixed and real
  Cyrillic text started flowing through, this crashed with
  `UnicodeEncodeError` trying to print it to a `cp1252` Windows console.
  Removed; it was debug output that should never have shipped.

### 6. `ProvenanceTracker` didn't create its own output directory

**Symptom:** `FileNotFoundError` on `ingestion_report.json`, the very last
step of the pipeline, after every other stage had already succeeded.

**Cause:** `CSVLoader` and `GarbageLoader` both call
`os.makedirs(os.path.dirname(path), exist_ok=True)` before writing.
`ProvenanceTracker.write()` didn't.

**Fix:** added the same line. Same bug class as #2 — a component writing
to disk without guaranteeing the path it's writing to exists — just three
files later and the last thing standing between a clean run and a crash.

## Result after fixes 1-6

```
python main.py
# Exit code 0.
# Stage 1: 38790 valid, 6 garbage.
# Stage 2: 38791 valid, 0 garbage.
# Deduplication: 64.35% duplicate rate (real -- see FIXED_SCHEMA_ETL_TUTORIAL.md
#   for why that number is plausible, not alarming, for this dataset).
```

## The hybrid: can content detection replace the hand-written schema?

Short answer: yes, exactly, on this file. `etl/schema_detection.py` detects
each of the 8 target fields' real column position using two signals —
content pattern matching for `email`/`phone` (the only two roles with a
reliable value pattern), and header name matching for everything else
(`firstname`, `lastname`, `address`, `city`, `zipcode`, `ip_address`, none
of which have a detectable value pattern — free text has no signature).

**It got one wrong on the first attempt**, and the fix is worth recording
as its own lesson: `ip_address` matched column 20 (`shipping_method`), not
column 28 (`ip`), because the synonym `"ip"` is a literal substring of
`"shipping"`, and the matcher checked substrings before exact matches —
so the false positive won before the real column was ever reached. Fixed
by checking for an **exact** header match across all unclaimed columns
first, falling back to substring matching only for roles still unresolved
after that. Same category of mistake as the leading-zero lesson in the
other tool's schema inference: a short, generic pattern matches more than
you meant it to, and the fix is almost always "prefer the more specific
signal first," not "abandon the general one."

After that fix, `main_hybrid.py` (same `Pipeline`, `DeduplicationEngine`,
`ValidationEngine`, `DataQualityEngine`, `ProvenanceTracker` as `main.py` —
only the schema-resolution step changed) detected all 8 fields correctly:

```
email        -> column  9  (content, match_rate 1.0)
phone        -> column 10  (content, match_rate 1.0)
firstname    -> column  7  (header_exact: "firstname")
lastname     -> column  8  (header_exact: "lastname")
address      -> column 13  (header_exact: "street")
city         -> column 12  (header_exact: "city")
zipcode      -> column 11  (header_exact: "postcode")
ip_address   -> column 28  (header_exact: "ip")
```

**Verified, not assumed:** `main_hybrid.py`'s final deduplicated output and
pre-dedup clean output are **byte-for-byte identical** to `main.py`'s
(`filecmp.cmp(..., shallow=False)` on both files, plus the stage-1 garbage
file too). Zero hand-authored field positions, same result.

### What wasn't ported over, and why

The hybrid's checkers (`_is_email`, `_is_phone`) are small, self-contained
re-implementations, not an import from the portfolio's `rules/` package,
even though `rules/schema.py` already has equivalent (and more complete)
versions. Both tools are headed for their own GitHub repos; a cross-repo
import would make neither one runnable on its own. The duplication is
small (a couple of regexes) and deliberate, not an oversight.

## Known gaps — found, then fixed (2026-11-07)

All four were fixed in the same session they were found in. Fix details:

- **`dq_engine.py`'s 100% missing-phone report.** Was already corrected to
  read `row.get("phone")` instead of `row.get("telephone")` by the time
  this was rechecked — confirmed fixed, `Missing phone: 0` now.
- **`validation_engine.py`'s ~99.9% "username errors."** The pattern was
  ASCII-only (`[a-zA-Z0-9&|#(). ]`); changed to `[\w&|#(). ]` with
  `re.UNICODE` — `\w` matches letters in any script in Python's `re` for
  `str` patterns, not just a-z/A-Z. Verified: username errors dropped from
  13810 to 3 on the real file, with the report's other numbers unchanged.
- **`detect_encoding()`'s dead code.** The real reason it was dead: every
  call site passed an explicit `encoding=`, *and* `CSVExtractor`'s default
  parameter value was the string `"latin-1"` (truthy), not `None` — so
  even a caller that passed nothing would never reach the
  `detect_encoding()` fallback branch. Fixed the default to `None`, and
  removed the explicit `encoding="utf-8"` from every `CSVExtractor` call
  in both `main.py` and `main_hybrid.py`, so `chardet`-based detection is
  now genuinely exercised on every run, not just theoretically available.
  Verified safe first: `chardet.detect()` on the real file reports
  `UTF-8-SIG` at 100% confidence, matching the strict-decode proof from
  bug #4 above. Reran both pipelines after the change — exit code 0,
  byte-identical final output to before.
- **`Extractor`'s type hint mismatch.** Changed the abstract method's
  return type from `Iterable[Dict[str, Any]]` to `Iterable[List[str]]`,
  matching what `CSVExtractor.extract()` actually yields, with a
  docstring explaining that the mapping onto named fields happens later,
  in the Transformer.

**Reconfirmed after all four fixes:** `main.py` and `main_hybrid.py` both
exit 0, and their final deduplicated/clean/garbage files are still
byte-for-byte identical to each other (same `filecmp.cmp(..., shallow=False)`
check as before) — none of these fixes changed the pipeline's actual
output, only the accuracy of its reporting and the correctness of
previously-unexercised code paths.

## Running either version

```powershell
pip install chardet pandas matplotlib
python main.py          # hand-mapped schema, datasets/samples/{to-be-ingested,completed,garbage}/
python main_hybrid.py   # detected schema, datasets/samples/hybrid/{...}/ -- same input file, same rules
python main_folder_batch.py  # every *.csv in datasets/samples/records/, schema detected per file
```

## Comparing against the exploratory notebook (`scoremark-validity-testing.ipynb`)

The notebook represents an earlier, more exploratory line of attack on the
same problem — several abandoned attempts at different source formats
(raw SQL `INSERT` dumps, NDJSON, Salesforce-shaped JSON) before converging
on something close to what `main.py` became, plus additional
post-processing refinements that never made it into `etl/`.

**Accuracy: `main.py`/`main_hybrid.py` are measurably more accurate on this
file.** Two findings prove it, from the notebook's own output:

- Its column-occupancy report (cell 19) shows `zipcode` at 0.0026% and
  `lastname` at 0.0052% populated — essentially erased, somewhere across
  its long chain of sequential file-to-file stages (each stage re-reads
  the previous stage's freshly-written file rather than carrying one
  validated schema through). Our tools populate both fields correctly for
  the overwhelming majority of real rows.
- Its deduplication step (cell 16) reports `Cleaned Records: 4` out of
  38,765 raw rows — 99.99% dropped. Most likely cause: an earlier stage
  lets invalid emails through as blank instead of rejecting the row, and
  pandas' `duplicated()` treats multiple blank values as duplicates of
  each other. Our actual duplicate rate on this file, for comparison, is
  64.35% — explainable (see `docs/FIXED_SCHEMA_ETL_TUTORIAL.md`), not
  alarming.
- Its name validation (cell 25) independently hits the exact same
  ASCII-only-pattern mistake already found and fixed in this project's own
  `validation_engine.py` — confirmation the fix was correct, not a new
  finding.

To be fair to it: a few ideas are genuinely better than what's currently
in `etl/` — real IPv4 octet-range validation, an attempted mojibake
repair, and a per-rejection-reason bar chart. Only the chart was ported
(below); the other two would need their own verification pass before
being trusted.

**Folder processing: real benefit, implemented in a safer shape.** The
notebook's `split_file()` chunks one huge file into 250MB pieces before
processing each independently — at this file's actual size (19.6MB), that
adds pure overhead for zero benefit, and its specific implementation has a
real bug: it never re-writes the header into chunks after the first one,
so every downstream stage would silently misread the first data row of
each later chunk as if no header existed.

What's genuinely useful is a different shape of the same idea:
**processing every whole file in a folder**, not pieces of one file.
Implemented as `etl_pipeline.run_pipeline_for_folder()` — takes a
`build_pipeline(input_path, output_path, garbage_path)` callback so it
stays agnostic to which schema/rules a particular tool uses, runs one
`Pipeline` per `*.csv` found, and keeps going if one file fails entirely
rather than aborting the whole batch. `main_folder_batch.py` demonstrates
it detecting a fresh schema per file (not assuming every file in the
folder shares one layout) against both `messy_sample_4.csv` and a genuine
50-row slice of the same file (`messy_sample_4_slice.csv`, created to
prove multi-file aggregation actually works, not synthetic data) —
aggregated totals (38790+48 valid, 6+1 garbage) matched each file's
individually-correct result exactly.

Also added: `RuleTracker.visualize()`, a bar chart of rejection reasons —
the one idea from the notebook worth keeping as-is, directly portable
without the accuracy risk the chunking and deduplication logic carried.

**Reconfirmed after both additions:** `main.py` and `main_hybrid.py` still
exit 0 and still produce byte-identical final output to each other —
`Pipeline.run()` now returns `(valid_count, garbage_count)` instead of
nothing, which neither entry point was relying on, and nothing else about
either pipeline changed.

## Charts were never actually being saved anywhere

Asked directly: were the deduplication/validation/rule-failure bar charts
being exported as image files for later viewing? No — `matplotlib`'s
active backend here is `tkagg`, an interactive GUI backend. `plt.show()`
opens a real window when a person runs `python main.py` by hand at a
desktop, but does nothing useful (no display to open a window on) once
this code runs inside a web server process -- which is exactly where it
was headed next, for the frontend work. Found and fixed before it became
a confusing failure there, not after.

Changed `DeduplicationEngine.visualize()`, `ValidationEngine.visualize()`,
and `RuleTracker.visualize()` to `plt.savefig(output_path)` +
`plt.close()` instead of `plt.show()`. Each takes a `reports_dir` and
writes a fixed filename into it (`deduplication.png`,
`validation_errors.png`, `rule_failures.png`). The entry points compute
that folder from the raw input's location with
`etl/report/report_paths.reports_dir_for()` --
`datasets/<dataset>/records/<raw>.csv` charts land in
`datasets/<dataset>/reports/` -- so each dataset's charts sit beside its
own data and one dataset's run can never overwrite another's.
(`ValidationEngine.report()` no longer saves its chart implicitly; the
entry point calls `validation.visualize(REPORTS_DIR)` like the others.) This is also exactly the shape a web route handler needs: run
the pipeline, save the chart to a known path, serve that file (or its
bytes) back to the browser -- no GUI, no blocking call, nothing that only
works on a desktop with a display attached.

## Standalone utilities ported from the notebook, kept separate on purpose

Two ideas from the notebook that were genuinely good (see the accuracy
comparison above) were added as standalone functions -- callable directly
wherever needed, deliberately **not** wired into `OrderDatasetTransformer`'s
rule list, so neither `main.py`'s nor `main_hybrid.py`'s already-verified
output changed by adding them.

- **`etl/utils/validators.py::is_valid_ipv4`** -- real octet-range
  checking (`999.999.999.999` has the right shape but isn't a real
  address), not just a shape-matching regex. Checked against the real
  file: `ip` is valid IPv4 on 37,839/38,795 rows (matching the
  column-occupancy report's ~97.5% figure almost exactly), and
  `forwarded_ip` is valid on all 19 rows where it's even populated.
- **`etl/utils/mojibake.py::repair_mojibake`** -- tries re-decoding text
  through a short list of candidate codecs (`latin-1`, `windows-1252`,
  `mac_roman`) and keeps the result only if it both succeeds and no
  longer shows mojibake markers; otherwise returns the input completely
  unchanged. Guarded by `looks_like_mojibake()` so it never attempts a
  "repair" on text that isn't actually showing signs of corruption.
  Verified by reproducing the *exact* corruption from bug #4 above
  (`"Александр".encode("utf-8").decode("latin-1")`, the same
  wrong-codec mistake that broke `firstname` originally) and confirming
  `repair_mojibake()` recovers the original string exactly.
  What it deliberately does not attempt: the pre-existing `?????`
  mojibake already noted in this file's `city`/`street` fields for some
  rows -- that's data already lost to a lossy conversion before this file
  was ever created, and no encoding trick recovers bytes that are
  already gone.

Both are available for a future per-file pass if wanted, without having
been forced into the pipeline that's already been verified correct.
