"""
SCORE-2: proves /analyze is actually calling rules/disposition.run_pipeline()
correctly, not just returning *a* 200. Per TESTING_STRATEGY.md, the
strongest version of this isn't "the messy sample produces some errors" --
it's an exact match against samples/injected_counts.json, the known,
provably-correct ground truth from Phase 3. A test built this way can be
independently checked by anyone reading the repo, without trusting
anything else.
"""

import json
import re
from pathlib import Path

import pytest

from app import app as flask_app

GROUND_TRUTH = json.loads(Path("samples/injected_counts.json").read_text())

RUN_ID_PATTERN = re.compile(r"/download/([0-9a-f]+)/report\.json")


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _get_report(client, sample: str) -> dict:
    """
    Posts to /analyze, extracts the run_id from the rendered results
    page's own download link, then fetches report.json through the real
    /download route -- exercising the same path a browser actually
    would, rather than reaching into the app's internals to grab the
    report directly.
    """
    response = client.post("/analyze", data={"sample": sample})
    assert response.status_code == 200

    body = response.get_data(as_text=True)
    match = RUN_ID_PATTERN.search(body)
    assert match, "results page did not contain a report.json download link"

    report_response = client.get(f"/download/{match.group(1)}/report.json")
    assert report_response.status_code == 200
    return json.loads(report_response.get_data(as_text=True))


def _find(rows: list[dict], column: str) -> dict:
    return next(row for row in rows if row["column"] == column)


def test_clean_sample_report_shows_zero_problems_everywhere(client):
    report = _get_report(client, "clean")

    assert all(row["missing_count"] == 0 for row in report["completeness"])
    assert report["uniqueness"]["duplicate_row_count"] == 0
    assert all(row["autocorrected_count"] == 0 for row in report["consistency"])


def test_messy_sample_report_matches_the_injected_ground_truth_exactly(client):
    report = _get_report(client, "messy")

    phone_completeness = _find(report["completeness"], "phone")
    assert phone_completeness["missing_count"] == GROUND_TRUTH["missing_phone_rows"]

    email_validity = _find(report["validity"], "email")
    assert email_validity["invalid_count"] == GROUND_TRUTH["invalid_email_rows"]

    assert report["uniqueness"]["duplicate_row_count"] == GROUND_TRUTH["duplicated_rows"]
    assert report["uniqueness"]["duplicate_group_count"] == GROUND_TRUTH["duplicated_rows"]

    # full_name is split into firstname + lastname; each inconsistent name
    # is fixed in both halves, and counted once per row.
    for column in ("firstname", "lastname"):
        assert _find(report["consistency"], column)["autocorrected_count"] == GROUND_TRUTH["inconsistent_name_rows"]
    assert report["structure"]["autocorrected_row_count"] == GROUND_TRUTH["inconsistent_name_rows"]


def test_messy_sample_garbage_count_equals_the_two_rejecting_problem_categories(client):
    # 9 = 4 invalid + 5 duplicates, with zero overlap between categories
    # (see samples/generate_samples.py's docstring on why each injected
    # problem lands on a disjoint set of rows). The 4 missing-phone rows are
    # NOT flagged: fields are optional, so a missing value is measured
    # (Completeness, occupancy) but never a reason to reject a row.
    response = flask_app.test_client().post("/analyze", data={"sample": "messy"})
    body = response.get_data(as_text=True)
    expected = GROUND_TRUTH["invalid_email_rows"] + GROUND_TRUTH["duplicated_rows"]
    assert f"{GROUND_TRUTH['messy_sample_row_count'] - expected} clean, {expected} flagged" in body


def test_a_real_upload_is_analyzed_through_the_same_pipeline_as_the_samples(client):
    # Not a sample -- a tiny, genuinely uploaded CSV with one obviously
    # missing value, proving the upload path reaches run_pipeline() too,
    # not just the two canned-sample paths.
    import io

    content = b"name,email\r\nLarry,larry@x.com\r\nJane,\r\n"
    data = {"file": (io.BytesIO(content), "tiny.csv")}
    response = client.post("/analyze", data=data, content_type="multipart/form-data")

    assert response.status_code == 200
    match = RUN_ID_PATTERN.search(response.get_data(as_text=True))
    assert match
    report = json.loads(
        client.get(f"/download/{match.group(1)}/report.json").get_data(as_text=True)
    )
    email_completeness = _find(report["completeness"], "email")
    assert email_completeness["missing_count"] == 1


def test_download_serves_the_clean_csv_with_real_content(client):
    response = client.post("/analyze", data={"sample": "clean"})
    match = RUN_ID_PATTERN.search(response.get_data(as_text=True))

    csv_response = client.get(f"/download/{match.group(1)}/clean.csv")
    assert csv_response.status_code == 200
    assert b"customer_id" in csv_response.data


def test_download_rejects_an_invalid_run_id(client):
    response = client.get("/download/not-a-real-run-id/clean.csv")
    assert response.status_code == 404


def test_download_rejects_a_path_traversal_attempt_in_run_id(client):
    response = client.get("/download/..%2F..%2F..%2Fetc/clean.csv")
    assert response.status_code == 404


def test_download_rejects_an_unrecognized_artifact_name(client):
    response = client.post("/analyze", data={"sample": "clean"})
    match = RUN_ID_PATTERN.search(response.get_data(as_text=True))

    bad_response = client.get(f"/download/{match.group(1)}/secret.txt")
    assert bad_response.status_code == 404
