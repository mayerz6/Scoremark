"""
Charts are written beside the raw dataset they describe:
datasets/<dataset>/records/<raw>.csv -> datasets/<dataset>/reports/.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: these tests only ever save files

import pandas as pd

from etl.report.deduplication_engine import DeduplicationEngine
from etl.report.report_paths import reports_dir_for
from etl.report.rule_tracker import RuleTracker
from etl.report.validation_engine import ValidationEngine


def test_raw_file_in_records_folder_reports_to_the_dataset_folder(tmp_path):
    raw = tmp_path / "datasets" / "reportage" / "records" / "customers.csv"
    assert reports_dir_for(raw) == tmp_path / "datasets" / "reportage" / "reports"


def test_records_folder_itself_reports_to_the_dataset_folder(tmp_path):
    records = tmp_path / "datasets" / "samples" / "records"
    records.mkdir(parents=True)
    assert reports_dir_for(records) == tmp_path / "datasets" / "samples" / "reports"


def test_raw_file_outside_a_records_folder_reports_beside_itself(tmp_path):
    raw = tmp_path / "exports" / "customers.csv"
    assert reports_dir_for(raw) == tmp_path / "exports" / "reports"


def test_relative_paths_used_by_the_entry_points():
    assert reports_dir_for("./datasets/reportage/records/x.csv").as_posix() == "datasets/reportage/reports"


def _final_csv(path):
    pd.DataFrame({
        "firstname": ["Larry", "Jane", "Jane"],
        "email": ["l@x.com", "j@x.com", "j@x.com"],
        "phone": ["1", "2", "2"],
    }).to_csv(path, index=False)


def test_every_chart_lands_in_the_given_reports_folder(tmp_path):
    reports = tmp_path / "datasets" / "demo" / "reports"
    final = tmp_path / "final.csv"
    _final_csv(final)

    dedup = DeduplicationEngine(str(final), subset_columns=["email", "phone"])
    deduplicated = dedup.run()
    validation = ValidationEngine(deduplicated)
    validation.run()
    tracker = RuleTracker()
    tracker.record_failure("EmailValidationRule")

    paths = [dedup.visualize(reports), validation.visualize(reports), tracker.visualize(reports)]

    assert {Path(p).name for p in paths} == {"deduplication.png", "validation_errors.png", "rule_failures.png"}
    assert all(Path(p).parent == reports for p in paths)
    assert sorted(f.name for f in reports.iterdir()) == [
        "deduplication.png", "rule_failures.png", "validation_errors.png",
    ]


def test_validation_run_no_longer_saves_a_chart_on_its_own(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # any implicit default path would land here
    final = tmp_path / "final.csv"
    _final_csv(final)

    ValidationEngine(str(final)).run()

    assert not (tmp_path / "datasets").exists()
