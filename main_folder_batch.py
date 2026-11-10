"""
Folder-based processing: every *.csv in a dataset's records/ folder goes
through the same ETL main.py runs, then the results are combined and
deduplicated as one dataset.

    datasets/<dataset>/
        confirmed_dataset_headers.py   <- the ONLY per-dataset thing edited by
                                          hand: final_schema.header lists the
                                          fields to extract, in output order
        records/*.csv                  <- raw input (any mix of encodings and
                                          , ; | or tab delimiters)
        batch/to-be-ingested/<file>    <- stage 1 output, per file
        batch/completed/<file>         <- stage 2 output, per file
        batch/garbage/                 <- rejected rows, per file and stage
        batch/final/combined.csv       <- every file's stage 2 output, + source_file
        batch/final/combined_deduplicated.csv   <- the deliverable
        batch/final/combined_duplicates.csv     <- what dedup removed, and from which file
        batch/metadata/ingestion_report.json    <- provenance
        reports/*.png                  <- charts: rule failures, deduplication,
                                          validation, occupancy (combined) and
                                          occupancy_<file> (one per raw file)

Order of operations, and why:

  1. Per file -- detect encoding, delimiter and column layout; stage 1
     (field cleaning + field-level quality rules: email, phone, minimum
     fields, ...); stage 2 (final sanitizing + enforcing the header's
     column layout). Every file is fully transformed and checked on its
     own first, so...
  2. ...combining only ever merges rows already in the same final shape,
     with the same normalization applied (lowercase-insensitive emails,
     digits-only phones) -- otherwise the same customer in two exports
     could look different and slip past dedup.
  3. Deduplicate the COMBINED file, not each file alone: a customer present
     in two exports is a duplicate too. First occurrence wins, in file-name
     order, then row order.
  4. Reports (validation, data-quality summary, charts, provenance) last,
     so they describe the deduplicated dataset that's actually delivered.
  5. The user decides what happens to the data artifacts: delete all,
     delete everything but the deliverable, or keep them (the default).
     Asked at the end when run from a terminal, or chosen up front with
     --delete-artifacts {all,intermediate,none}. Raw records and reports
     are never deleted -- see etl/cleanup.py.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from dq_engine import DataQualityEngine
from etl import cleanup
from etl.dataset_headers import load_final_schema
from etl.extract.csv_extractor import CSVExtractor
from etl.load.csv_loader import CSVLoader, GarbageLoader
from etl.report.deduplication_engine import DeduplicationEngine
from etl.report.occupancy import occupancy_report
from etl.report.provenance_tracker import ProvenanceTracker
from etl.report.report_paths import dataset_dir_for, reports_dir_for
from etl.report.rule_tracker import RuleTracker
from etl.report.validation_engine import ValidationEngine
from etl.schema_detection import detect_schema
from etl.transform.transformer import (
    AddressCleaningRule,
    BasicCleaningRule,
    CharacterSanitizationRule,
    DateNormalizationRule,
    EmailValidationRule,
    MinFieldRule,
    OrderDatasetTransformer,
    OrderDatasetTransformerStage2,
    PhoneValidationRule,
    SchemaEnforcementRule,
)
from etl.utils.encoding import detect_delimiter, detect_encoding
from etl_pipeline import Pipeline

RECORDS_FOLDER = "./datasets/samples/records"

#: Same dedup key as main.py. Columns missing from a dataset's header are
#: skipped; a row with every key column blank is never a duplicate.
DEDUP_KEY = ["email", "phone"]

#: Columns ValidationEngine reads -- it's skipped for a dataset without them.
VALIDATION_COLUMNS = {"email", "firstname"}

SOURCE_COLUMN = "source_file"

tracker = RuleTracker()


def stage_1_rules():
    return [
        CharacterSanitizationRule(),
        BasicCleaningRule(),
        EmailValidationRule(),
        PhoneValidationRule(),
        AddressCleaningRule(),
        DateNormalizationRule(),
        MinFieldRule(min_non_empty=3),
    ]


def stage_2_rules(final_schema):
    return [CharacterSanitizationRule(), SchemaEnforcementRule(final_schema)]


def build_pipeline(input_path, output_path, garbage_path, final_schema=None, rule_tracker=None) -> Pipeline:
    """
    Stage 1 for one raw file. Column layout is detected fresh per file --
    files in one folder can order their columns differently -- looking for
    exactly the fields listed in the dataset's confirmed_dataset_headers.py.

    Encoding and delimiter are detected per file too, and the same values
    are handed to CSVExtractor, so detection and extraction always read the
    file the same way.
    """
    if final_schema is None:
        final_schema = load_final_schema(dataset_dir_for(input_path))
    rule_tracker = rule_tracker or tracker

    encoding = detect_encoding(input_path)
    delimiter = detect_delimiter(input_path, encoding)

    with open(input_path, encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader)
        sample_rows = [row for row, _ in zip(reader, range(500))]

    detected_schema, confidence = detect_schema(header, sample_rows, roles=final_schema.header)

    print(f"  encoding={encoding}, delimiter={delimiter!r}")
    for role, idx in detected_schema.field_indices.items():
        print(f"    {role:12s} -> column {idx:2d}  ({confidence[role]['method']})")
    unresolved = [r for r in final_schema.header if confidence.get(r, {}).get("method") == "unresolved"]
    if unresolved:
        print(f"    NOT FOUND (output column left blank): {', '.join(unresolved)}")

    pipeline = Pipeline(
        extractor=CSVExtractor(input_path, schema=detected_schema, delimiter=delimiter, encoding=encoding),
        transformer=OrderDatasetTransformer(detected_schema, stage_1_rules(), rule_tracker),
        loader=CSVLoader(output_path, final_schema.header),
        garbage_loader=GarbageLoader(garbage_path),
    )
    pipeline.detection = {
        "encoding": encoding,
        "delimiter": delimiter,
        "field_indices": dict(detected_schema.field_indices),
        "confidence": confidence,
        "unresolved_fields": unresolved,
    }
    return pipeline


def _remove(*paths):
    """Deletes this run's own target files up front: Pipeline only writes a
    garbage file when there IS garbage, so a stale one from an earlier run
    would otherwise survive and be mistaken for this run's."""
    for path in paths:
        if os.path.exists(path):
            os.remove(path)


def process_file(input_path: Path, final_schema, batch_dir: Path, rule_tracker) -> dict:
    name = input_path.name
    stage_1_out = batch_dir / "to-be-ingested" / name
    stage_2_out = batch_dir / "completed" / name
    garbage_1 = batch_dir / "garbage" / f"garbage_{name}"
    garbage_2 = batch_dir / "garbage" / f"garbage_stage2_{name}"
    _remove(stage_1_out, stage_2_out, garbage_1, garbage_2)

    stage_1 = build_pipeline(str(input_path), str(stage_1_out), str(garbage_1), final_schema, rule_tracker)
    valid_1, rejected_1 = stage_1.run()

    stage_2 = Pipeline(
        extractor=CSVExtractor(str(stage_1_out), schema=final_schema, delimiter=",", encoding="utf-8"),
        transformer=OrderDatasetTransformerStage2(final_schema, stage_2_rules(final_schema), rule_tracker),
        loader=CSVLoader(str(stage_2_out), final_schema.header),
        garbage_loader=GarbageLoader(str(garbage_2)),
    )
    valid_2, rejected_2 = stage_2.run()

    return {
        "stage_2_output": stage_2_out,
        "artifacts": [str(p) for p in (stage_1_out, stage_2_out, garbage_1, garbage_2) if p.exists()],
        "stage_1": {"valid": valid_1, "garbage": rejected_1},
        "stage_2": {"valid": valid_2, "garbage": rejected_2},
        "detection": stage_1.detection,
        "error": None,
    }


def combine(stage_2_outputs: list[tuple[str, Path]], final_schema, combined_path: Path) -> int:
    """
    Concatenates every file's stage-2 output (already in the identical
    final_schema layout) into one file, tagging each row with the raw file
    it came from. Values are copied as text, untouched.
    """
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    header = list(final_schema.header)
    count = 0

    with open(combined_path, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=header + [SOURCE_COLUMN], extrasaction="ignore")
        writer.writeheader()
        for source_name, path in stage_2_outputs:
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    row[SOURCE_COLUMN] = source_name
                    writer.writerow(row)
                    count += 1

    return count


def run_batch(records_folder: str = RECORDS_FOLDER, delete_artifacts: str | None = None) -> dict:
    """
    delete_artifacts: what to delete once the reports exist -- "all",
    "intermediate" (keep only combined_deduplicated.csv) or "none". None
    asks interactively when run from a terminal, and keeps everything
    otherwise (e.g. when called from a script or test).
    """
    records = Path(records_folder)
    dataset_dir = dataset_dir_for(records)
    final_schema = load_final_schema(dataset_dir)
    batch_dir = dataset_dir / "batch"
    reports_dir = reports_dir_for(records)
    rule_tracker = RuleTracker()

    print(f"Dataset: {dataset_dir}  |  fields: {', '.join(final_schema.header)}")

    # ---- 1. per file: transform + field-level checks ----
    per_file = {}
    raw_files = sorted(p for p in records.iterdir() if p.is_file() and p.suffix.lower() == ".csv")
    for raw in raw_files:
        print(f"\n=== {raw.name} ===")
        try:
            per_file[raw.name] = process_file(raw, final_schema, batch_dir, rule_tracker)
        except Exception as error:  # one bad file never stops the batch
            print(f"FAILED to process {raw.name}: {error}")
            per_file[raw.name] = {"error": f"{type(error).__name__}: {error}"}

    succeeded = [(name, r["stage_2_output"]) for name, r in per_file.items() if not r["error"]]

    # ---- 2. combine ----
    combined = batch_dir / "final" / "combined.csv"
    combined_rows = combine(succeeded, final_schema, combined)
    print(f"\nCombined {len(succeeded)} file(s) -> {combined} ({combined_rows} rows)")

    # ---- 3. deduplicate the combined dataset ----
    dedup_key = [c for c in DEDUP_KEY if c in final_schema.header]
    dedup = DeduplicationEngine(str(combined), subset_columns=dedup_key)
    deduplicated = dedup.run()

    # ---- 4. reports on what's actually delivered ----
    validation = None
    if VALIDATION_COLUMNS <= set(final_schema.header) and dedup.records_clean:
        validation = ValidationEngine(deduplicated)
        validation.run()
    else:
        print(f"\nValidation skipped (needs columns {sorted(VALIDATION_COLUMNS)} and at least one row).")

    dq = DataQualityEngine(
        file_path=deduplicated,
        rules=[EmailValidationRule(), PhoneValidationRule(), AddressCleaningRule(), MinFieldRule(min_non_empty=3)],
    )
    dq.run()

    # Occupancy: each file's density once in final shape, then the whole
    # deduplicated dataset's (source_file is bookkeeping, not a field).
    occupancy_per_file = {}
    occupancy_charts = {}
    for name, path in succeeded:
        occupancy_per_file[name], occupancy_charts[name] = occupancy_report(
            path, reports_dir, filename=f"occupancy_{Path(name).stem}.png", title=name,
        )
    occupancy_combined, occupancy_chart = occupancy_report(
        deduplicated, reports_dir, filename="occupancy.png",
        title=f"{dataset_dir.name} (combined, deduplicated)", exclude_columns=(SOURCE_COLUMN,),
    )

    charts = {
        "rule_failures": rule_tracker.visualize(reports_dir),
        "deduplication": dedup.visualize(reports_dir),
        "validation_errors": validation.visualize(reports_dir) if validation else None,
        "occupancy": occupancy_chart,
        "occupancy_per_file": {k: str(v) if v else None for k, v in occupancy_charts.items()},
    }

    summary = {
        "dataset": str(dataset_dir),
        "fields": list(final_schema.header),
        "dedup_key": dedup_key,
        "files": {
            name: {k: v for k, v in r.items() if k not in ("stage_2_output", "artifacts")}
            for name, r in per_file.items()
        },
        "failed_files": [name for name, r in per_file.items() if r["error"]],
        "combined_rows": combined_rows,
        "duplicates_removed": dedup.records_duplicates,
        "final_rows": dedup.records_clean,
        "rule_failures": dict(rule_tracker.failures),
        "validation": {
            "email_errors": len(validation.email_errors),
            "username_errors": len(validation.username_errors),
        } if validation else None,
        "missing_email": dq.missing_email,
        "missing_phone": dq.missing_phone,
        "occupancy_pct": {"combined": occupancy_combined, "per_file": occupancy_per_file},
        "outputs": {
            "combined": str(combined),
            "deduplicated": deduplicated,
            "duplicates": str(combined).replace(".csv", "_duplicates.csv"),
            "charts": {k: (v if isinstance(v, dict) else str(v) if v else None) for k, v in charts.items()},
            "artifacts": {
                "intermediate": [p for r in per_file.values() for p in r.get("artifacts", [])]
                                + [str(combined), str(combined).replace(".csv", "_duplicates.csv")],
                "final": [deduplicated],
            },
        },
        "artifacts_deleted": None,
    }
    provenance = ProvenanceTracker(str(batch_dir / "metadata" / "ingestion_report.json"))
    provenance.write(summary)

    print("\n----- Folder Batch Summary -----")
    print(f"Files: {len(raw_files)} ({len(summary['failed_files'])} failed)")
    print(f"Combined rows: {combined_rows}  |  duplicates removed: {dedup.records_duplicates}"
          f"  |  final rows: {dedup.records_clean}")

    # ---- 5. the user decides what happens to the data artifacts ----
    if delete_artifacts is None:
        delete_artifacts = cleanup.ask_scope() if sys.stdin.isatty() else "none"
    to_delete = cleanup.select_artifacts(summary["outputs"]["artifacts"], delete_artifacts)
    if to_delete:
        deleted = cleanup.delete_artifacts(to_delete, allowed_root=batch_dir)
        summary["artifacts_deleted"] = {"scope": delete_artifacts, "files": deleted}
        provenance.write(summary)  # the report records what was removed, and when
        print(f"Deleted {len(deleted)} artifact file(s) ({delete_artifacts}). Reports and raw records kept.")
    else:
        print("ETL artifacts kept.")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the batch ETL over a dataset's records/ folder.")
    parser.add_argument("records_folder", nargs="?", default=RECORDS_FOLDER,
                        help=f"folder of raw CSVs (default: {RECORDS_FOLDER})")
    parser.add_argument("--delete-artifacts", choices=cleanup.SCOPES, default=None,
                        help="delete data artifacts after the reports are written, without asking: "
                             "'all', 'intermediate' (keep combined_deduplicated.csv) or 'none'. "
                             "Omit to be asked at the end.")
    args = parser.parse_args()
    run_batch(args.records_folder, delete_artifacts=args.delete_artifacts)
