# Scoremark — Testing Strategy

Last updated: 2026-11-09

## The question this answers

Not "does it have tests" — "how do we know, with evidence rather than
confidence, that the site is doing what it claims to do." That's a
stricter bar, and it's the one this project has followed since Phase 1:
every claim this tool makes should be checked against a number someone
can verify, not just asserted.

## The three tiers, and what each one is actually for

| Tier | Tool | Speed | Answers |
|---|---|---|---|
| Unit | `pytest` against `rules/` directly | Milliseconds | Does one rule function (completeness, validity, uniqueness, consistency, schema inference) do the right thing for every input worth checking? |
| Route / integration | `pytest` + Flask's `app.test_client()` | Sub-second | Does a real HTTP request through the actual Flask app produce the right response -- right status code, right content, right rejection? |
| Browser / UI | Playwright | Seconds per test | Does a real browser, with real JavaScript, actually let a visitor complete the task -- select a file, see a chart render, download a result? |

This mirrors the same shape already proven on the portfolio's PHP side
(`docs/PHPUNIT_TUTORIAL.md`'s Unit/Smoke tiers there) and on the
Athlene reference project's smoke/UI split
(`docs/reference/SMOKE_TESTING_TUTORIAL.md`,
`docs/reference/UI_TESTING_TUTORIAL.md`) -- same underlying pattern,
different language. If you've internalized one, you already understand
the shape of the other two.

### Why Flask doesn't need a disposable server the way the PHP tools did

The PHP Smoke suite had to start a real `php -S` process because PHP has
no in-process way to simulate an HTTP request against your own app.
Flask does: `app.test_client()` drives the exact same routing and
request-handling code a real server would, in the same process, without
sockets or a subprocess. `tests/test_web_routes.py` uses this already --
no `SmokeServer`-equivalent needed for this tier. A real running server
only becomes necessary for the browser tier, because a browser (unlike
`test_client()`) needs an actual port to point at.

## The indicator that actually matters most: ground-truth-backed assertions

A test that asserts "the messy sample produces some errors" is weak --
it would pass even if the rules were subtly wrong. The strong version,
already possible today because of work done in Phase 3, is to assert the
**exact** numbers:

```python
import json

with open("samples/injected_counts.json") as f:
    ground_truth = json.load(f)

response = client.post("/analyze", data={"sample": "messy"})
report = extract_report_from_response(response)  # once SCORE-2 exists

assert report["completeness_missing_phone"] == ground_truth["missing_phone_rows"]
assert report["validity_invalid_email"] == ground_truth["invalid_email_rows"]
assert report["uniqueness_duplicate_count"] == ground_truth["duplicated_rows"]
assert report["consistency_autocorrected_name"] == ground_truth["inconsistent_name_rows"]
```

This is the same proof structure as `tests/Smoke/BlogJourneyTest.php` and
`tests/test_disposition.py` on the other two tools in this repo: an
injected, known quantity of each problem, and a test that fails loudly
the moment the reported count drifts from it. Write this test as soon as
SCORE-2 lands -- it's the single highest-value test in this whole app,
because it's the one a reviewer can independently verify against
`samples/injected_counts.json` without trusting anything else.

## What to test at each tier, concretely

**Unit (already done, 36 tests):** every rule module, schema inference,
delimiter detection, CSV structure errors. No new work needed here unless
the rules themselves change.

**Route/integration (SCORE-1 has the first 7; grows with each ticket):**
- `GET /` renders both sample buttons and the upload form (done).
- `POST /analyze` with each sample produces the exact ground-truth
  numbers above (write this with SCORE-2).
- Oversized/wrong-type/malformed upload is rejected with a clear status,
  not a 500 (write this with SCORE-5 -- the test should exist *before*
  the guard does, so it's red first and green once the guard lands, the
  same discipline the main portfolio's PORT-20 ticket followed).
- `GET /download/<run_id>/<artifact>` serves the right file; an invalid
  `run_id` 404s, not 500s (write with SCORE-4/SCORE-6).
- Rate limiting actually throttles the Nth+1 request (write with SCORE-8).

**Browser/UI (Playwright, once the above tiers are solid):**
- Selecting a file and submitting shows the results view with real
  content, not just "the page didn't crash."
- A Chart.js canvas actually renders (non-trivial canvas content, not an
  empty one).
- The client-side size check (SCORE-7) blocks an oversized file *before*
  a request is sent — check this by asserting no network request fires,
  not just that an error message appears.
- A download link actually produces a downloaded file with the expected
  name.

Don't start this tier before the route tier is solid — a flaky browser
test covering logic a fast Python test could already cover is wasted
test-suite weight, the same principle the PHPUnit tutorial's tier
ordering was built on.

## The indicator worth putting in the README, for the audience this is actually for

A technical reviewer skimming a GitHub repo for 30 seconds doesn't read
test files. They read one line in the README. The honest, specific
version of that line — once the full suite above exists — is something
like:

> 40+ automated tests cover the four data-quality rules, schema
> inference, and the upload/analyze/download flow, including an exact
> match against a known, injected set of data problems. Run with
> `pytest`.

That's a stronger signal than "fully tested" precisely because it names
a number and a specific, checkable claim (the injected-count match)
instead of an adjective. Update the number as the suite grows; don't
let it go stale.

## CI

Once `SCORE-11` (own GitHub repo) exists: GitHub Actions running `pytest`
on every push, same staged-pipeline shape as the main portfolio's
`TESTING_CICD_STRATEGY.md` describes (syntax/lint stage first, fast
tests next, slower browser tests last, nothing merges on red). Not worth
building before there's a repo for it to run against.
