"""
SCORE-1: proves the upload + sample-selection form actually round-trips
over real HTTP semantics (Flask's test_client() drives real request/
response handling, just without spawning a separate server process --
see TESTING_STRATEGY.md for why that's enough at this tier and where a
real running server becomes necessary instead).
"""

import io

import pytest

from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_index_page_renders_both_sample_buttons(client):
    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "clean sample" in body.lower()
    assert "messy sample" in body.lower()


def test_index_page_renders_the_upload_form(client):
    response = client.get("/")
    body = response.get_data(as_text=True)

    assert 'type="file"' in body
    assert 'enctype="multipart/form-data"' in body


def test_analyze_accepts_the_clean_sample_reference(client):
    response = client.post("/analyze", data={"sample": "clean"})
    assert response.status_code == 200


def test_analyze_accepts_the_messy_sample_reference(client):
    response = client.post("/analyze", data={"sample": "messy"})
    assert response.status_code == 200


def test_analyze_accepts_a_real_file_upload(client):
    data = {"file": (io.BytesIO(b"a,b\n1,2\n"), "test.csv")}
    response = client.post("/analyze", data=data, content_type="multipart/form-data")

    assert response.status_code == 200
    assert "test.csv" in response.get_data(as_text=True)


def test_analyze_rejects_a_request_with_neither_sample_nor_file(client):
    # Nothing in the request at all -- the stub's one real branch of
    # logic worth a test of its own, independent of SCORE-2's eventual
    # real processing.
    response = client.post("/analyze", data={})
    assert response.status_code == 400


def test_analyze_rejects_an_unrecognized_sample_name(client):
    # Not "clean" or "messy" -- must not be silently accepted as if it
    # were a real sample.
    response = client.post("/analyze", data={"sample": "not-a-real-sample"})
    assert response.status_code == 400


# --- SCORE-5: upload guards, exercised through the real endpoint ---
# These mirror tests/test_upload_guards.py's unit tests, but prove the
# checks are actually wired into /analyze, not just correct in isolation.

def test_analyze_rejects_a_file_with_the_wrong_extension(client):
    data = {"file": (io.BytesIO(b"a,b\n1,2\n"), "not_a_csv.txt")}
    response = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert ".csv" in response.get_data(as_text=True)


def test_analyze_rejects_an_empty_file(client):
    data = {"file": (io.BytesIO(b""), "empty.csv")}
    response = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "empty" in response.get_data(as_text=True).lower()


def test_analyze_rejects_binary_content_disguised_as_csv(client):
    data = {"file": (io.BytesIO(b"\x00\x01\x02not really text"), "fake.csv")}
    response = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "binary" in response.get_data(as_text=True).lower()


def test_analyze_rejects_a_csv_with_too_many_rows(client):
    header = "a,b\n"
    rows = "1,2\n" * 20_001  # one past MAX_ROWS
    content = (header + rows).encode("utf-8")
    data = {"file": (io.BytesIO(content), "too_many_rows.csv")}
    response = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "rows" in response.get_data(as_text=True).lower()


def test_analyze_rejects_a_csv_with_too_many_columns(client):
    header = ",".join(f"col{i}" for i in range(51)) + "\n"  # one past MAX_COLUMNS
    row = ",".join(str(i) for i in range(51)) + "\n"
    content = (header + row).encode("utf-8")
    data = {"file": (io.BytesIO(content), "too_many_columns.csv")}
    response = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "columns" in response.get_data(as_text=True).lower()


def test_analyze_accepts_a_file_that_passes_every_guard(client):
    data = {"file": (io.BytesIO(b"a,b\n1,2\n3,4\n"), "fine.csv")}
    response = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "fine.csv" in body
    assert "2 rows analyzed" in body


def test_analyze_rejects_a_file_over_the_flask_content_length_cap(client):
    # Bigger than FLASK_MAX_CONTENT_LENGTH itself (the outer Werkzeug-level
    # cap), not just over MAX_FILE_SIZE_BYTES -- this is the 413 path,
    # a different mechanism than the 400s above.
    oversized_content = b"a,b\n" + (b"1,2\n" * 1_000_000)  # well over 2MB + headroom
    data = {"file": (io.BytesIO(oversized_content), "huge.csv")}
    response = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert response.status_code == 413
    assert "too large" in response.get_data(as_text=True).lower()


# --- Real-world uploads: other encodings, malformed rows ---

def _upload(client, content: bytes, name="upload.csv"):
    data = {"file": (io.BytesIO(content), name)}
    return client.post("/analyze", data=data, content_type="multipart/form-data")


@pytest.mark.parametrize("encoding", ["utf-16", "utf-8-sig", "cp1252"])
def test_analyze_accepts_non_utf8_exports(client, encoding):
    response = _upload(client, "name,city\nJosé,Montréal\nAnn,Québec\n".encode(encoding))
    assert response.status_code == 200
    assert "2 rows analyzed" in response.get_data(as_text=True)


def test_one_malformed_row_no_longer_rejects_the_whole_file(client):
    content = b"name,email\nLarry,l@x.com\nAlamo, Kamal,k@x.com\nJane,j@x.com\n"
    response = _upload(client, content)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "3 rows analyzed" in body
    assert "1 malformed row(s)" in body


def test_unparseable_upload_error_names_the_file_not_a_python_object(client):
    response = _upload(client, b"\n\n", name="blank_lines.csv")
    body = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "blank_lines.csv" in body
    assert "BytesIO" not in body


# --- Visitor-initiated deletion ---

def _run_id(response):
    import re
    return re.search(r"/download/([0-9a-f]{32})/", response.get_data(as_text=True)).group(1)


def test_results_page_offers_a_delete_button(client):
    body = _upload(client, b"a,b\n1,2\n").get_data(as_text=True)
    assert "Delete my data now" in body
    assert 'method="post"' in body


def test_delete_removes_every_artifact_of_the_run(client):
    run_id = _run_id(_upload(client, b"a,b\n1,2\n"))
    assert client.get(f"/download/{run_id}/clean.csv").status_code == 200

    response = client.post(f"/delete/{run_id}")
    assert response.status_code == 200
    assert "has been deleted" in response.get_data(as_text=True)
    for artifact in ("clean.csv", "garbage.csv", "report.json"):
        assert client.get(f"/download/{run_id}/{artifact}").status_code == 404

    # Deleting again is harmless, and says there's nothing left.
    again = client.post(f"/delete/{run_id}")
    assert again.status_code == 404
    assert "Nothing to delete" in again.get_data(as_text=True)


def test_delete_only_accepts_post(client):
    run_id = _run_id(_upload(client, b"a,b\n1,2\n"))
    assert client.get(f"/delete/{run_id}").status_code == 405
    assert client.get(f"/download/{run_id}/clean.csv").status_code == 200


@pytest.mark.parametrize("bad_id", ["..%2F..%2Fetc", "not-a-run", "A" * 32, "0" * 31])
def test_delete_rejects_anything_that_is_not_a_run_id(client, bad_id):
    assert client.post(f"/delete/{bad_id}").status_code == 404
