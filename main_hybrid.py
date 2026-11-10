"""
The hybrid version of main.py: same batch pipeline (two stages, dedup,
independent validation, provenance), but stage 1's DatasetSchema is
detected from the file's own header + content (etl/schema_detection.py)
instead of hand-written in datasets/samples/order_dataset.py.

Writes to ./datasets/samples/hybrid/... (a separate tree from main.py's
output) specifically so the two runs' final files can be diffed against
each other afterward -- see docs/ETL_HANDOFF.md for that comparison.
"""

import csv

from datasets.samples.confirmed_dataset_headers import final_schema
from dq_engine import DataQualityEngine
from etl.extract.csv_extractor import CSVExtractor
from etl.load.csv_loader import CSVLoader, GarbageLoader
from etl.report.deduplication_engine import DeduplicationEngine
from etl.report.provenance_tracker import ProvenanceTracker
from etl.report.occupancy import occupancy_report
from etl.report.report_paths import reports_dir_for
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
from etl_pipeline import Pipeline

RAW_FILE = "./datasets/samples/records/messy_sample_4.csv"
REPORTS_DIR = reports_dir_for(RAW_FILE)  # -> ./datasets/samples/reports
SAMPLE_ROW_COUNT = 500  # enough for a stable content match rate, cheap even on a huge file


def sniff_schema(path: str, delimiter: str):
    # No encoding passed to the raw open() here either -- chardet (via
    # etl/utils/encoding.py) decides it, same as CSVExtractor now does by
    # default. Confirmed separately that chardet reports 'UTF-8-SIG' at
    # 100% confidence for this exact file before relying on it here.
    from etl.utils.encoding import detect_encoding
    encoding = detect_encoding(path)

    with open(path, encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader)
        sample_rows = []
        for row in reader:
            sample_rows.append(row)
            if len(sample_rows) >= SAMPLE_ROW_COUNT:
                break

    return detect_schema(header, sample_rows)


def main():
    detected_schema, confidence = sniff_schema(RAW_FILE, delimiter=";")

    print("----- Detected Schema -----")
    for role, idx in detected_schema.field_indices.items():
        print(f"  {role:12s} -> column {idx:2d}  ({confidence[role]})")

    stage_1_rules = [
        CharacterSanitizationRule(),
        BasicCleaningRule(),
        EmailValidationRule(),
        PhoneValidationRule(),
        AddressCleaningRule(),
        DateNormalizationRule(),
        MinFieldRule(min_non_empty=3),
    ]
    stage_2_rules = [
        CharacterSanitizationRule(),
        SchemaEnforcementRule(final_schema),
    ]

    tracker = RuleTracker()

    pipeline = Pipeline(
        extractor=CSVExtractor(RAW_FILE, schema=detected_schema, delimiter=";"),
        transformer=OrderDatasetTransformer(detected_schema, stage_1_rules, tracker),
        loader=CSVLoader("./datasets/samples/hybrid/to-be-ingested/processed_dataset.csv", final_schema.header),
        garbage_loader=GarbageLoader("./datasets/samples/hybrid/garbage/garbage_dataset.csv"),
    )
    pipeline.run()

    stage_2_pipeline = Pipeline(
        extractor=CSVExtractor("./datasets/samples/hybrid/to-be-ingested/processed_dataset.csv",
                                schema=final_schema, delimiter=","),
        transformer=OrderDatasetTransformerStage2(final_schema, stage_2_rules, tracker),
        loader=CSVLoader("./datasets/samples/hybrid/completed/samples_final.csv", final_schema.header),
        garbage_loader=GarbageLoader("./datasets/samples/hybrid/garbage/garbage_dataset_2.csv"),
    )
    stage_2_pipeline.run()

    dedup_engine = DeduplicationEngine(
        input_file="./datasets/samples/hybrid/completed/samples_final.csv",
        subset_columns=["email", "phone"],
    )
    deduplicated_file = dedup_engine.run()

    validation = ValidationEngine(deduplicated_file)
    validation.run()
    validation.visualize(REPORTS_DIR)
    occupancy_report(deduplicated_file, REPORTS_DIR, title="Hybrid sample dataset")

    dq_engine = DataQualityEngine(
        file_path=deduplicated_file,
        rules=[EmailValidationRule(), PhoneValidationRule(), AddressCleaningRule(), MinFieldRule(min_non_empty=3)],
    )
    dq_engine.run()

    provenance = ProvenanceTracker("./datasets/samples/hybrid/metadata/ingestion_report.json")
    provenance.write({
        "dataset": "Generated Sample Dataset (hybrid, auto-detected schema)",
        "detected_schema": {role: idx for role, idx in detected_schema.field_indices.items()},
        "detection_confidence": confidence,
        "stage1_output": "processed_dataset.csv",
        "stage2_output": "samples_final.csv",
        "deduplicated_output": deduplicated_file,
        "rows_processed": dq_engine.total_rows,
        "missing_email": dq_engine.missing_email,
        "missing_phone": dq_engine.missing_phone,
    })


if __name__ == "__main__":
    main()
