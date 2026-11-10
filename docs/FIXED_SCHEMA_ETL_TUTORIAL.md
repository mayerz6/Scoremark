# Fixed-Schema ETL Tutorial: How `main.py` Actually Works

This documents the batch ETL tool built in `etl/`, `etl_pipeline.py`, `dq_engine.py`,
and `main.py` — the tool that takes one specific, known-shape raw export
(`datasets/samples/records/messy_sample_4.csv`, a 34-column, semicolon-delimited
order export) and turns it into a deduplicated, validated, standardized
dataset. Same three-pass teaching style as `docs/PHPUNIT_TUTORIAL.md`: plain
English, the code, what the result actually means — except here there's no
pass/fail, there's a *pipeline run*, and "what it means" is reading a
summary report instead of a green checkmark.

If you're looking for the *other* tool (`rules/`, driving `analyze.py`),
that one infers a file's schema from its content and is built to handle
*any* uploaded CSV. This tool is the opposite design, on purpose: you tell
it exactly where every field lives, in exchange for a much larger, more
capable pipeline (two transform stages, deduplication, independent
validation, a provenance record) than a general-purpose tool could safely
assume. `docs/ETL_HANDOFF.md` covers why both exist and the real bugs that
were found getting this one to run cleanly.

**Does this apply to the hybrid version (`main_hybrid.py`)?** Mostly yes.
Every part of this tutorial from Step 3 onward (cleaning rules, clean/garbage
routing, stage 2, deduplication, validation, provenance) is identical code,
unchanged, for both versions — `main_hybrid.py` builds the exact same
`Pipeline`, `DeduplicationEngine`, `ValidationEngine`, `DataQualityEngine`,
and `ProvenanceTracker` objects. The only difference is Part 2's Steps 1-2:
instead of a hand-written `DatasetSchema`, the hybrid detects one from the
file's own header and content (`etl/schema_detection.py`). That's also the
answer to "does it just take any file and handle everything" — no. The
hybrid still only knows how to *locate* these 8 specific fields
(firstname, lastname, email, phone, address, city, zipcode, ip_address) —
it reads a file's structure automatically instead of needing someone to
hand-count column positions for *this* file, but it isn't a generic "any
file in, cleaned file out" tool. That more general job is what the other
tool (`rules/`) is for.

---

## Part 0: The four pieces, and how they fit together

| Piece | File | Job |
|---|---|---|
| `DatasetSchema` | `etl/schema.py` | A frozen, immutable description of "what fields exist, and at what raw column position." Nothing more. |
| `Extractor` | `etl/extract/csv_extractor.py` | Opens a file, reads it row by row, hands back raw rows as plain lists of strings. Doesn't know what the fields *mean*. |
| `Transformer` | `etl/transform/transformer.py` | Takes one raw row, maps it onto the schema's named fields, and runs it through a list of **rules** — small objects that each either fix something or reject the row outright. |
| `Loader` | `etl/load/csv_loader.py` | Writes a finished batch of rows (or rejected ones) to a CSV. |
| `Pipeline` | `etl_pipeline.py` | The conductor: pulls rows from the extractor, pushes each one through the transformer, and routes the result to the loader (valid) or the garbage loader (rejected). |

The whole design rests on one idea: **a raw CSV row is just a list of
strings, with no names attached, until something tells it what each
position means.** `DatasetSchema` is that "something." Everything else —
`CSVExtractor`, `OrderDatasetTransformer` — is built to consume whatever
`field_indices` a `DatasetSchema` hands it, without caring where those
indices came from. (That last sentence is the exact seam `docs/ETL_HANDOFF.md`'s
hybrid version plugs into later — it generates a `DatasetSchema`
automatically instead of someone hand-writing one.)

---

## Part 1: Plain English — what `main.py` actually does, start to finish

1. Read the raw order export, 34 columns, no reliable assumption about
   which ones matter.
2. Pull out just the 8 fields this pipeline cares about (first/last name,
   email, phone, address, city, zip, IP), by their known positions in the
   raw file.
3. Clean each one up — strip quotes, normalize phone digits, title-case
   addresses — and reject outright anything missing too much to be useful.
4. Write the survivors to a clean, 8-column file; write everything rejected
   to a garbage file, unchanged, so nothing is lost.
5. Re-read that clean 8-column file, re-validate it against the simpler
   schema it now has (sequential columns 0-7), and write a second,
   doubly-confirmed clean file.
6. Remove duplicate customers (same email + phone) from that file.
7. Independently re-check emails and names for format problems — a second
   opinion, using different code than step 3's rules.
8. Produce a plain data-quality report: how many rows, how many missing
   emails/phones, the most common email domains.
9. Write one JSON file recording what happened — which files were
   produced, how many rows survived each stage — so the run leaves a
   record of itself.

Nine steps, and each one is a single object instantiated and run in
`main()`. That mapping — one English sentence, one Python object — is the
whole design philosophy of this tool.

---

## Part 2: The code, mapped to each step

### Step 1-2: Extraction + field mapping

```python
extractor = CSVExtractor(
    "./datasets/samples/records/messy_sample_4.csv",
    schema=schema,          # order_dataset.py -- real positions in the 34-column file
    delimiter=";",
    encoding="utf-8",
)
```

`CSVExtractor.extract()` is deliberately dumb:

```python
def extract(self):
    with open(self.file_path, encoding=self.encoding, newline="") as f:
        reader = csv.reader(f, delimiter=self.delimiter)
        for row in reader:
            if len(row) < self.schema.required_min_columns:
                continue   # not enough columns to even attempt a mapping
            yield row
```

It hands back a plain `list[str]` per row — `['210', '0', 'INV201300', ...]`
— no field names yet. `required_min_columns` is computed from the schema
itself (`max(field_indices.values()) + 1`), so a row that's too short to
possibly contain every mapped field is dropped before wasting any further
work on it.

The actual mapping happens in the transformer, not the extractor:

```python
class OrderDatasetTransformer:
    def transform(self, raw_record):
        transformed = {}
        for field, idx in self.schema.field_indices.items():
            transformed[field] = raw_record[idx].strip() if idx < len(raw_record) else ""
        ...
```

`schema.field_indices` is `{"firstname": 7, "lastname": 8, "email": 9, ...}`
— so this loop is doing exactly nine lookups like `raw_record[7]`,
`raw_record[9]`, labeling each one with the name it's supposed to have.
**This line is where the entire pipeline's correctness lives or dies** —
see the sidebar below.

> **Why this is the one line worth being paranoid about.** This is
> positional access: `raw_record[9]` is trusted to be an email because the
> schema *says* position 9 is email, not because anything checked. If the
> wrong `DatasetSchema` ever gets passed in here — which is exactly what
> happened during development (see `docs/ETL_HANDOFF.md`) — this line
> doesn't error. It just silently labels the wrong data with the wrong
> name, and the mistake doesn't surface until a validation rule three
> steps later rejects everything for reasons that look unrelated. Nothing
> about this one line can catch that mistake; only comparing its output
> against what you expected can.

### Step 3: Cleaning and rejection rules

```python
stage_1_rules = [
    CharacterSanitizationRule(),
    BasicCleaningRule(),
    EmailValidationRule(),
    PhoneValidationRule(),
    AddressCleaningRule(),
    DateNormalizationRule(),
    MinFieldRule(min_non_empty=3),
]
```

Every rule shares one shape — `apply(record) -> record | None` — which is
what lets them be listed and run in sequence:

```python
for rule in self.rules:
    transformed = rule.apply(transformed)
    if transformed is None:
        return None   # this row is garbage now; stop running rules on it
```

Returning the record means "keep going." Returning `None` means "reject,"
and no later rule in the list even runs. `EmailValidationRule` is a clean
example of a *rejecting* rule:

```python
def apply(self, record):
    email = record.get("email", "")
    email = email.replace(" ", "").replace('"', '')...
    if not EMAIL_PATTERN.fullmatch(email.lower()):
        return None
    return record
```

`AddressCleaningRule` is the opposite kind — a *fixing* rule, never
rejects, only reshapes:

```python
def apply(self, record):
    address = record.get("address")
    if not address:
        return record
    address = address.replace(",", " ").replace(".", " ")...
    record["address"] = self.to_camel_case(address)
    return record
```

The rule list mixes both kinds freely, in the order that makes sense:
sanitize characters first, validate format-sensitive fields next, clean
cosmetic fields last.

### Step 4: Routing to clean vs. garbage

This is `Pipeline.run()`, the conductor:

```python
for raw in self.extractor.extract():
    result = self.transformer.transform(raw)
    if result:
        valid.append(result)
    else:
        garbage.append(raw)

self.loader.load(valid)
if garbage:
    self.garbage_loader.load(garbage)
```

Note what goes where: `garbage.append(raw)` appends the **original raw
row**, not the partially-transformed one — a rejected row is preserved
exactly as it arrived, so `garbage_dataset.csv` is always something you can
cross-reference against the source file by eye.

### Steps 5-6: A second pass, a simpler schema

Stage 2 re-reads stage 1's own output:

```python
stage_2_pipeline = Pipeline(
    extractor=CSVExtractor("./datasets/samples/to-be-ingested/processed_dataset.csv",
                            schema=final_schema, delimiter=",", encoding="utf-8"),
    transformer=OrderDatasetTransformerStage2(final_schema, stage_2_rules, tracker),
    ...
)
```

`final_schema` (from `confirmed_dataset_headers.py`) has simple, sequential
indices — `{"firstname": 0, "lastname": 1, ...}` — because by this point the
file *is* just those 8 columns, in that order; there's no 34-column raw
layout left to map around. This is why two different `DatasetSchema`
objects exist at all: one describes the messy original, one describes the
clean shape stage 1 produces. Using the wrong one for the wrong stage is
exactly the bug this tool shipped with the first time (again, see
`docs/ETL_HANDOFF.md`) — the fix was swapping which schema each stage uses,
not changing either schema's contents.

### Step 7: Deduplication

```python
dedup_engine = DeduplicationEngine(
    input_file="./datasets/samples/completed/samples_final.csv",
    subset_columns=["email", "phone"],
)
deduplicated_file = dedup_engine.run()
```

This one drops pandas-level, not row-by-row Python:

```python
df = pd.read_csv(self.input_file, low_memory=False)
mask_duplicates = df.duplicated(subset=["email", "phone"], keep="first")
cleaned_df = df[~mask_duplicates]
duplicates_df = df[mask_duplicates]
```

Two customers count as "the same" here if their email *and* phone both
match — `keep="first"` means whichever row appears earliest in the file
survives, every later match is dropped. On the real order export, this
rate came out at 64% — plausible, not alarming, once you know the dataset:
a huge share of orders share the literal placeholder email
`noreply@test.ru`, so "same email + phone" catches a lot of genuinely
repeat (or guest-checkout) customers, not a data bug.

### Step 8: A second, independent validation pass

```python
validation = ValidationEngine(deduplicated_file)
validation.run()
```

This is deliberately **not** the same code as stage 1's
`EmailValidationRule` — it's a second, separately-written regex check
(`validate_emails`), run over the *already-cleaned* file as a sanity check
that stage 1's rules actually did their job, rather than trusting stage 1
blindly. Two independent implementations agreeing is stronger evidence
than one implementation being confident in itself.

### Step 9: The provenance record

```python
tracker = ProvenanceTracker("./datasets/samples/metadata/ingestion_report.json")
tracker.write({
    "dataset": "Generated Sample Dataset",
    "stage1_output": "processed_dataset.csv",
    "rows_processed": dq_engine.total_rows,
    "missing_email": dq_engine.missing_email,
    "missing_phone": dq_engine.missing_phone,
})
```

One JSON file, timestamped, naming every output file this run produced and
a few headline numbers. Small, but it's the difference between "a file
exists somewhere" and "a record exists of when it was made, from what, and
with what result" — the second one is what makes a pipeline's output
trustworthy months later.

---

## Part 3: Reading a run's result

There's no pass/fail here — there's a summary to read and interpret. A
healthy run on this dataset currently looks like:

```
----- ETL Summary -----
Valid rows: 38790
Garbage rows: 6

----- ETL Summary -----
Valid rows: 38791
Garbage rows: 0

DEDUPLICATION REPORT
--------------------
Raw Records: 38791
Clean Records: 13828
Dropped Duplicates: 24963
Duplicate Rate: 64.35%

VALIDATION REPORT
------------------
Rows Tested: 13828
Email Errors: 1
Username Errors: 13810
```

Reading this correctly matters as much as producing it:

- **38790/38796 valid in stage 1** means the extraction and field mapping
  are basically sound — only 6 rows didn't have enough real data to pass
  `MinFieldRule`.
- **64.35% duplicate rate** is a real, explainable number for this
  specific dataset (see Step 7 above), not evidence of a bug by itself.
- **3 "username errors" out of 13828**, now that `validate_usernames()`
  accepts Unicode letters instead of ASCII-only — this is what that number
  looks like once the rule actually matches what the data is. (It read
  13810 before that fix; `docs/ETL_HANDOFF.md` has the full story of why,
  if you want to see what "the rule doesn't match the data's actual
  alphabet" looks like before it's fixed.)

---

## Running it

```powershell
pip install chardet pandas matplotlib
python main.py
```

Outputs land under `datasets/samples/`: `to-be-ingested/` (stage 1 clean),
`completed/` (stage 2 clean + deduplicated), `garbage/` (every rejected
row, both stages), `metadata/ingestion_report.json` (the provenance
record).
