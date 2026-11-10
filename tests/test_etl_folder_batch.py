"""
End-to-end: main_folder_batch.run_batch() over a dataset folder --
per-file transform, combine, deduplicate the combined set, report.
"""

import csv
import json

import matplotlib

matplotlib.use("Agg")

import pandas as pd
import pytest

from etl.dataset_headers import DatasetHeadersError, load_final_schema
from etl.report.deduplication_engine import DeduplicationEngine
from etl.schema_detection import detect_schema
from main_folder_batch import run_batch

HEADERS = ("firstname", "lastname", "email", "phone", "provider")


def _dataset(tmp_path, headers=HEADERS):
    dataset = tmp_path / "datasets" / "demo"
    (dataset / "records").mkdir(parents=True)
    (dataset / "confirmed_dataset_headers.py").write_text(
        "from etl.schema import DatasetSchema\n"
        f"final_schema = DatasetSchema(header={tuple(headers)!r}, field_indices={{}})\n"
    )
    return dataset


def _write(path, encoding, delimiter, rows):
    with open(path, "w", newline="", encoding=encoding) as f:
        csv.writer(f, delimiter=delimiter).writerows(rows)


def _filler(prefix, n=22):
    return [[f"{prefix}{i} Last{i}", f"{prefix.lower()}{i}@example.com", f"05{i:08d}", "acme"] for i in range(n)]


@pytest.fixture
def batch(tmp_path):
    dataset = _dataset(tmp_path)
    header = ["name", "email", "phone", "provider"]

    # File A: UTF-16, comma. File B: UTF-8 with BOM, semicolon, different
    # column order. Kamal is in both (email cased differently); Larry and
    # Jane have neither email nor phone -- different people, never duplicates.
    _write(dataset / "records" / "a_export.csv", "utf-16", ",", [header] + [
        ["Kamal Alamo", "kamal@x.com", "0562020114", "acme"],
        ["Larry Mayers", "", "", "acme"],
    ] + _filler("A"))
    _write(dataset / "records" / "b_export.csv", "utf-8-sig", ";",
           [["provider", "phone", "email", "name"]] + [
               ["globex", "0562020114", "KAMAL@x.com", "Kamal Alamo"],
               ["globex", "", "", "Jane Doe"],
           ] + [list(reversed(r)) for r in _filler("B")])

    # Stale garbage from an imaginary earlier run must not survive.
    stale = dataset / "batch" / "garbage" / "garbage_b_export.csv"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale")

    summary = run_batch(str(dataset / "records"))
    final = pd.read_csv(summary["outputs"]["deduplicated"], dtype=str, keep_default_na=False)
    return dataset, summary, final


def test_files_are_combined_then_deduplicated_across_files(batch):
    _, summary, final = batch
    assert summary["combined_rows"] == 2 + 22 + 2 + 22
    assert summary["duplicates_removed"] == 1  # Kamal, from b_export (first occurrence wins)
    assert summary["final_rows"] == 47
    kamal = final[final["firstname"] == "Kamal"]
    assert kamal["source_file"].tolist() == ["a_export.csv"]


def test_people_without_email_or_phone_are_never_collapsed(batch):
    _, _, final = batch
    assert {"Larry", "Jane"} <= set(final["firstname"])


def test_values_are_preserved_as_text(batch):
    _, _, final = batch
    assert "0562020114" in final["phone"].tolist()  # leading zero intact


def test_hand_listed_custom_field_is_extracted(batch):
    _, summary, final = batch
    assert set(final["provider"]) == {"acme", "globex"}
    assert summary["files"]["a_export.csv"]["detection"]["unresolved_fields"] == []


def test_name_is_split_and_no_header_rows_leak_into_the_output(batch):
    _, _, final = batch
    assert final.loc[final["firstname"] == "Larry", "lastname"].tolist() == ["Mayers"]
    assert "firstname" not in final["firstname"].tolist()
    assert "name" not in final["firstname"].tolist()


def test_reports_metadata_and_stale_files(batch):
    dataset, summary, _ = batch
    assert sorted(p.name for p in (dataset / "reports").iterdir()) == [
        "deduplication.png", "occupancy.png", "occupancy_a_export.png", "occupancy_b_export.png", "validation_errors.png",
    ]
    report = json.loads((dataset / "batch" / "metadata" / "ingestion_report.json").read_text())
    assert report["final_rows"] == 47 and report["failed_files"] == []
    assert not (dataset / "batch" / "garbage" / "garbage_b_export.csv").exists()
    duplicates = pd.read_csv(summary["outputs"]["duplicates"], dtype=str)
    assert duplicates["source_file"].tolist() == ["b_export.csv"]


def test_one_unreadable_file_does_not_stop_the_batch(tmp_path):
    dataset = _dataset(tmp_path)
    _write(dataset / "records" / "good.csv", "utf-8", ",", [["name", "email", "phone", "provider"]] + _filler("G"))
    (dataset / "records" / "broken.csv").write_bytes(b"")

    summary = run_batch(str(dataset / "records"))
    assert summary["failed_files"] == ["broken.csv"]
    assert summary["final_rows"] == 22


def test_missing_headers_file_is_a_clear_error(tmp_path):
    (tmp_path / "records").mkdir()
    with pytest.raises(DatasetHeadersError, match="confirmed_dataset_headers.py"):
        run_batch(str(tmp_path / "records"))


def test_column_positions_come_from_header_order_not_the_file(tmp_path):
    dataset = _dataset(tmp_path, headers=("email", "firstname"))
    schema = load_final_schema(dataset)
    assert schema.field_indices == {"email": 0, "firstname": 1}
    assert schema.has_header is True


def test_custom_field_matches_header_exactly_never_by_substring():
    rows = [["x", "p@x.com"]] * 25
    schema, _ = detect_schema(["Provider ID", "email"], rows, roles=("provider", "email"))
    assert "provider" not in schema.field_indices
    schema, _ = detect_schema(["Provider", "email"], rows, roles=("provider", "email"))
    assert schema.field_indices["provider"] == 0


# ---------- DeduplicationEngine on its own (also used by main.py) ----------

def test_dedup_mask_rules():
    df = pd.DataFrame({
        "email": ["a@x.com", " A@X.com", "", "", "b@x.com"],
        "phone": ["1", "1", "", "", ""],
    })
    mask = DeduplicationEngine.duplicate_mask(df, ["email", "phone"])
    # case/space-insensitive match caught; two all-blank keys kept.
    assert mask.tolist() == [False, True, False, False, False]


# ---------- user-chosen artifact deletion after reports ----------

def _small_dataset(tmp_path):
    dataset = _dataset(tmp_path)
    _write(dataset / "records" / "one.csv", "utf-8", ",", [["name", "email", "phone", "provider"]] + _filler("O"))
    _write(dataset / "records" / "two.csv", "utf-8", ",",
           [["name", "email", "phone", "provider"], ["Bad Row", "not-an-email", "1", "x"]] + _filler("T"))
    return dataset


def _data_files(dataset):
    return sorted(p.relative_to(dataset).as_posix() for p in (dataset / "batch").rglob("*.csv"))


def test_default_without_a_terminal_keeps_every_artifact(tmp_path):
    dataset = _small_dataset(tmp_path)
    summary = run_batch(str(dataset / "records"))
    assert summary["artifacts_deleted"] is None
    assert "batch/final/combined_deduplicated.csv" in _data_files(dataset)


def test_delete_all_removes_every_data_file_but_keeps_reports_and_raw_input(tmp_path):
    dataset = _small_dataset(tmp_path)
    summary = run_batch(str(dataset / "records"), delete_artifacts="all")

    assert _data_files(dataset) == []
    assert sorted(p.name for p in (dataset / "records").iterdir()) == ["one.csv", "two.csv"]
    assert (dataset / "reports" / "deduplication.png").exists()
    report = json.loads((dataset / "batch" / "metadata" / "ingestion_report.json").read_text())
    assert report["artifacts_deleted"]["scope"] == "all"
    assert len(report["artifacts_deleted"]["files"]) == len(summary["artifacts_deleted"]["files"]) > 0


def test_delete_intermediate_keeps_only_the_deliverable(tmp_path):
    dataset = _small_dataset(tmp_path)
    run_batch(str(dataset / "records"), delete_artifacts="intermediate")
    assert _data_files(dataset) == ["batch/final/combined_deduplicated.csv"]


def test_cleanup_refuses_paths_outside_the_batch_folder(tmp_path):
    from etl.cleanup import delete_artifacts

    raw = tmp_path / "records" / "keep.csv"
    raw.parent.mkdir()
    raw.write_text("a\n1\n")
    (tmp_path / "batch").mkdir()
    with pytest.raises(ValueError, match="outside"):
        delete_artifacts([str(raw)], allowed_root=tmp_path / "batch")
    assert raw.exists()


# ---------- empty records + occupancy ----------

def test_empty_records_go_to_garbage_under_their_own_rule(tmp_path):
    dataset = _dataset(tmp_path)
    rows = [["name", "email", "phone", "provider"]] + _filler("E") + [["", "", "", ""], [" ", "", "  ", ""]]
    _write(dataset / "records" / "with_blanks.csv", "utf-8", ",", rows)

    summary = run_batch(str(dataset / "records"))

    assert summary["rule_failures"] == {"EmptyRecord": 2}
    assert summary["files"]["with_blanks.csv"]["stage_1"] == {"valid": 22, "garbage": 2}
    garbage = (dataset / "batch" / "garbage" / "garbage_with_blanks.csv").read_text().splitlines()
    assert len(garbage) == 2


def test_occupancy_reports_each_file_and_the_combined_dataset(tmp_path):
    dataset = _dataset(tmp_path)
    header = ["name", "email", "phone", "provider"]
    # "full": every field filled. "sparse": half the phones empty, providers NULL.
    _write(dataset / "records" / "full.csv", "utf-8", ",", [header] + _filler("F", 20))
    sparse = [[f"S{i} L{i}", f"s{i}@example.com", f"06{i:08d}" if i % 2 else "", "NULL"] for i in range(20)]
    _write(dataset / "records" / "sparse.csv", "utf-8", ",", [header] + sparse)

    summary = run_batch(str(dataset / "records"))
    occ = summary["occupancy_pct"]

    assert occ["per_file"]["full.csv"]["phone"] == 100.0
    assert occ["per_file"]["sparse.csv"]["phone"] == 50.0
    assert occ["per_file"]["sparse.csv"]["provider"] == 0.0  # "NULL" is not a value
    assert occ["combined"]["phone"] == 75.0
    assert "source_file" not in occ["combined"]
    for chart in ("occupancy.png", "occupancy_full.png", "occupancy_sparse.png"):
        assert (dataset / "reports" / chart).exists()
