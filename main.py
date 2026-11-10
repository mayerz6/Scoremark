from etl.config import AppConfig 
from datasets.reportage.order_dataset import schema
from datasets.reportage.confirmed_dataset_headers import final_schema
from etl.schema import DatasetSchema
from etl.extract.csv_extractor import CSVExtractor
from etl_pipeline import Pipeline
from dq_engine import DataQualityEngine
from etl.transform.transformer import AddressCleaningRule, CharacterSanitizationRule, SchemaEnforcementRule, PhoneValidationRule, OrderDatasetTransformer, OrderDatasetTransformerStage2, BasicCleaningRule, EmailValidationRule, MinFieldRule, DateNormalizationRule
from etl.load.csv_loader import CSVLoader, GarbageLoader
from etl.report.rule_tracker import RuleTracker
from etl.report.deduplication_engine import DeduplicationEngine
from etl.report.streaming_deduplication_engine import StreamingDeduplicator
from etl.report.validation_engine import ValidationEngine
from etl.report.provenance_tracker import ProvenanceTracker
from etl.report.occupancy import occupancy_report
from etl.report.report_paths import reports_dir_for

RAW_FILE = "./datasets/reportage/records/reportageempire_customers.csv"
REPORTS_DIR = reports_dir_for(RAW_FILE)  # -> ./datasets/reportage/reports


# ----------------------------
# Entrypoint
# ----------------------------
def main():

    stage_1_rules = [
    CharacterSanitizationRule(),
    BasicCleaningRule(),
    EmailValidationRule(),
    PhoneValidationRule(),
    AddressCleaningRule(),
    DateNormalizationRule(),
    MinFieldRule(min_non_empty=3)
    ]

    stage_2_rules = [
    CharacterSanitizationRule(),
    SchemaEnforcementRule(schema),
    ]

    tracker = RuleTracker()

    pipeline = Pipeline(
        extractor=CSVExtractor(RAW_FILE, schema=schema, delimiter=","),
        transformer=OrderDatasetTransformer(schema, stage_1_rules, tracker),
        loader=CSVLoader(f"./datasets/reportage/to-be-ingested/processed_reportageempire_customers.csv", final_schema.header),
        garbage_loader=GarbageLoader(f"./datasets/reportage/garbage/garbage_reportageempire_customers.csv")
    )
    pipeline.run()

    stage_2_pipeline = Pipeline(
        extractor=CSVExtractor(f"./datasets/reportage/to-be-ingested/processed_reportageempire_customers.csv", schema=final_schema, delimiter=","),
        transformer=OrderDatasetTransformerStage2(final_schema, stage_2_rules, tracker),
        loader=CSVLoader(f"./datasets/reportage/completed/reportageempire_customers_final.csv", final_schema.header),
        garbage_loader=GarbageLoader(f"./datasets/reportage/garbage/garbage_reportageempire_customers.csv")
    )
    stage_2_pipeline.run()


    dedup_engine = DeduplicationEngine(

        input_file="./datasets/reportage/completed/reportageempire_customers_final.csv",

        subset_columns=[
            "email", 
            "phone"
        ]
    )

    deduplicated_file = dedup_engine.run()

    dedup_engine.visualize(REPORTS_DIR)

    validation = ValidationEngine(
        deduplicated_file
                )

    validation.run()
    validation.visualize(REPORTS_DIR)
    occupancy_report(deduplicated_file, REPORTS_DIR, title="Reportage Empire customers")

    dq_engine = DataQualityEngine(
        file_path=deduplicated_file,
        rules=[
            EmailValidationRule(),
            PhoneValidationRule(),
            AddressCleaningRule(),
            MinFieldRule(min_non_empty=3)
        ]
    )

    # schema=schema
    dq_engine.run()


    tracker = ProvenanceTracker(
        "./datasets/reportage/metadata/ingestion_report.json"
    )

    tracker.write({

        "dataset": "Reportage Empire Customers Dataset",

        "stage1_output": "reportageempire_customers.csv",

        "stage2_output": "reportageempire_customers_final.csv",

        "deduplicated_output": "reportageempire_customers_final_deduplicated.csv",

        "rows_processed": dq_engine.total_rows,

        "missing_email": dq_engine.missing_email,

        "missing_phone": dq_engine.missing_phone

    })


if __name__ == "__main__":
    main()