"""
SCORE-8: Flask-Limiter's in-memory storage lives on the module-level
`limiter` object in app.py, shared across the whole pytest process --
not reset between tests the way a fresh test_client() might suggest.

Without this, test_web_routes.py's dozen-plus POSTs to /analyze (plus
every other test file that happens to hit that route) would eventually
trip the "10 per minute" limit and start failing with 429s that have
nothing to do with what each test is actually checking.

autouse=True so every test in the suite gets a clean counter, not just
the rate-limiting tests themselves.
"""

import pytest

from app import limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    limiter.reset()
    yield
