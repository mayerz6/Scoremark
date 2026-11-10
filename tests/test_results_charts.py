"""
SCORE-3: proves the results page actually wires Chart.js and real data
together. Flask's test_client() can't execute JavaScript or render a
canvas (that's the browser/Playwright tier -- see TESTING_STRATEGY.md),
so what's checked here is the layer below that: the right elements exist,
the Chart.js library is actually loaded, and the embedded JSON blob the
charts read from contains the exact, ground-truth-correct numbers -- not
just "a canvas is present somewhere."
"""

import json
import re
from pathlib import Path

import pytest

from app import app as flask_app

GROUND_TRUTH = json.loads(Path("samples/injected_counts.json").read_text())


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _chart_data_from(body: str) -> dict:
    match = re.search(
        r'<script id="chart-data" type="application/json">(.*?)</script>', body, re.DOTALL
    )
    assert match, "results page did not embed the chart-data JSON blob"
    return json.loads(match.group(1))


def test_results_page_includes_chart_js_and_both_canvases(client):
    response = client.post("/analyze", data={"sample": "messy"})
    body = response.get_data(as_text=True)

    assert "cdn.jsdelivr.net/npm/chart.js" in body
    assert 'id="overviewChart"' in body
    assert 'id="columnChart"' in body


def test_results_page_shows_one_stat_card_per_rule(client):
    response = client.post("/analyze", data={"sample": "messy"})
    body = response.get_data(as_text=True)

    for label in ("Completeness", "Validity", "Uniqueness", "Consistency"):
        assert label in body


def test_messy_sample_stat_cards_match_the_injected_ground_truth(client):
    response = client.post("/analyze", data={"sample": "messy"})
    body = response.get_data(as_text=True)

    stat_numbers = re.findall(r'<span class="stat-number">([^<]+)</span>', body)
    total_rows = GROUND_TRUTH["messy_sample_row_count"]

    expected_completeness_pct = f"{round(100 - GROUND_TRUTH['missing_phone_rows'] / (total_rows * 7) * 100, 2)}%"
    expected_duplicate_pct = f"{round(GROUND_TRUTH['duplicated_rows'] / total_rows * 100, 2)}%"

    assert stat_numbers == [
        expected_completeness_pct,
        str(GROUND_TRUTH["invalid_email_rows"]),
        expected_duplicate_pct,
        str(GROUND_TRUTH["inconsistent_name_rows"]),
    ]


def test_messy_sample_chart_data_blob_matches_the_injected_ground_truth(client):
    response = client.post("/analyze", data={"sample": "messy"})
    chart_data = _chart_data_from(response.get_data(as_text=True))

    total_rows = GROUND_TRUTH["messy_sample_row_count"]
    phone_index = chart_data["columns"].index("phone")
    email_index = chart_data["columns"].index("email")

    assert chart_data["missing_pct"][phone_index] == round(
        GROUND_TRUTH["missing_phone_rows"] / total_rows * 100, 2
    )
    assert chart_data["invalid_pct"][email_index] == round(
        GROUND_TRUTH["invalid_email_rows"] / total_rows * 100, 2
    )


def test_clean_sample_chart_data_is_all_zero(client):
    response = client.post("/analyze", data={"sample": "clean"})
    chart_data = _chart_data_from(response.get_data(as_text=True))

    assert all(value == 0.0 for value in chart_data["missing_pct"])
    assert all(value == 0 for value in chart_data["invalid_pct"])


def test_results_page_works_for_a_real_upload_too(client):
    # SCORE-3's "page works whether the run came from a sample or a real
    # upload" acceptance criterion, checked directly rather than assumed
    # from the sample-path tests above.
    import io

    content = b"name,email\nLarry,larry@x.com\nJane,not-an-email\n"
    data = {"file": (io.BytesIO(content), "tiny.csv")}
    response = client.post("/analyze", data=data, content_type="multipart/form-data")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="columnChart"' in body
    chart_data = _chart_data_from(body)
    assert "email" in chart_data["columns"]


# --- Dataset occupancy ---

def test_results_page_includes_the_occupancy_chart(client):
    body = client.post("/analyze", data={"sample": "messy"}).get_data(as_text=True)
    assert 'id="occupancyChart"' in body
    assert "Dataset occupancy" in body


def test_messy_sample_occupancy_is_the_inverse_of_missing_and_sorted_densest_first(client):
    chart_data = _chart_data_from(client.post("/analyze", data={"sample": "messy"}).get_data(as_text=True))
    total_rows = GROUND_TRUTH["messy_sample_row_count"]

    occupancy = dict(zip(chart_data["occupancy_columns"], chart_data["occupancy_pct"]))
    assert occupancy["phone"] == round(100 - GROUND_TRUTH["missing_phone_rows"] / total_rows * 100, 2)
    assert all(occupancy[c] == 100.0 for c in occupancy if c != "phone")
    assert chart_data["occupancy_pct"] == sorted(chart_data["occupancy_pct"], reverse=True)
    assert chart_data["occupancy_columns"][-1] == "phone"


def test_occupancy_treats_null_placeholders_as_unfilled(client):
    import io

    content = b"name,provider\nLarry,acme\nJane,NULL\nBob,\nAnn,N/A\n"
    data = {"file": (io.BytesIO(content), "tiny.csv")}
    chart_data = _chart_data_from(
        client.post("/analyze", data=data, content_type="multipart/form-data").get_data(as_text=True)
    )
    occupancy = dict(zip(chart_data["occupancy_columns"], chart_data["occupancy_pct"]))
    # "name" is split; single-word names leave lastname empty.
    assert occupancy == {"firstname": 100.0, "lastname": 0.0, "provider": 25.0}


def test_empty_records_go_to_garbage_and_do_not_dilute_occupancy(client):
    import io

    content = b"name,email\nLarry,l@x.com\n,\n , \nJane,\n"
    data = {"file": (io.BytesIO(content), "tiny.csv")}
    body = client.post("/analyze", data=data, content_type="multipart/form-data").get_data(as_text=True)

    assert "4 rows analyzed" in body
    assert "2 clean, 2 flagged" in body
    assert "2 empty record(s)" in body
    occupancy = dict(zip(_chart_data_from(body)["occupancy_columns"], _chart_data_from(body)["occupancy_pct"]))
    assert occupancy == {"firstname": 100.0, "lastname": 0.0, "email": 50.0}
