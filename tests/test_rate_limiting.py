"""
SCORE-8: proves the "10 per minute" limit on /analyze is real for uploads
and that canned samples are genuinely exempt, not just configured to look
that way. See tests/conftest.py for why each test here starts from a
clean counter rather than relying on test order.
"""

import io

import pytest

from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _upload(client, name: str = "fine.csv"):
    data = {"file": (io.BytesIO(b"a,b\n1,2\n"), name)}
    return client.post("/analyze", data=data, content_type="multipart/form-data")


def test_uploads_beyond_the_per_minute_limit_are_rejected_with_429(client):
    for _ in range(10):
        response = _upload(client)
        assert response.status_code == 200

    eleventh = _upload(client)
    assert eleventh.status_code == 429
    assert "too many requests" in eleventh.get_data(as_text=True).lower()


def test_canned_samples_are_exempt_from_the_upload_rate_limit(client):
    # Exhaust the limit with real uploads first...
    for _ in range(10):
        assert _upload(client).status_code == 200
    assert _upload(client).status_code == 429

    # ...then prove the samples still go through regardless.
    assert client.post("/analyze", data={"sample": "clean"}).status_code == 200
    assert client.post("/analyze", data={"sample": "messy"}).status_code == 200
