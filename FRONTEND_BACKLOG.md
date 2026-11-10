# Scoremark — Frontend/Deployment Backlog (Jira-style)

Project key: `SCORE`. Generated 2026-11-09 from `ARCHITECTURE_HANDOFF.md`.
Priorities: **P0** blocks anything else working, **P1** needed for a
usable v1, **P2** polish/stretch.

Scope reminder from the architecture doc: everything here touches the
Flask app (`app.py`, new templates/static assets) and calls into `rules/`
as an existing, unmodified library. Nothing here should require changing
`rules/disposition.py`, `rules/schema.py`, or any of the four rule
modules -- if a ticket below seems to need that, stop and re-check against
`ARCHITECTURE_HANDOFF.md` before proceeding.

---

## Epic: SCORE-CORE — Flask App Core

### SCORE-1 — Build the upload + sample-selection form
**Type:** Feature | **Priority:** P0 | **Status: Done (2026-11-09)**

**Description:** `GET /` renders a page with the two canned-sample buttons
(clean/messy, per `scoremark_project.md`'s Input section) and a file
upload form, both posting to the same analyze endpoint.

**Acceptance Criteria:**
- Canned sample buttons submit a reference (`?sample=clean` /
  `?sample=messy`), never re-uploading the bundled file's bytes.
- Upload form is a standard multipart POST, works without JavaScript
  (progressive enhancement, matching the rest of this portfolio's stated
  principle).

**Built:** `app.py` (`GET /`, stub `POST /analyze`), `templates/index.html`,
`static/css/style.css`. `/analyze` is intentionally a stub -- returns a
plain acknowledgment, doesn't call `run_pipeline()` yet (that's SCORE-2,
sequenced after SCORE-5's safety guards on purpose). 7 new route tests in
`tests/test_web_routes.py` (Flask `test_client()`, no server process
needed -- see `TESTING_STRATEGY.md`), full suite 59/59 passing. Visually
confirmed against the real dev server, not just the test client.

---

### SCORE-2 — Wire `POST /analyze` to `rules/disposition.run_pipeline()`
**Type:** Feature | **Priority:** P0 | **Status: Done (2026-11-09)**

**Description:** The actual integration point between the web layer and
the existing, tested engine. Accepts either `?sample=` or an uploaded
file, reads it via `rules/io.read_csv_as_text()`, calls
`run_pipeline()` exactly as `analyze.py` already does.

**Acceptance Criteria:**
- Canned-sample path and upload path converge on the same `run_pipeline()`
  call -- no duplicated logic between them.
- Output (`report`, `clean_df`, `garbage_df`) is written to a per-request
  location (see SCORE-6) and the report is handed to the results template.
- `rules/` itself is not modified to make this work.

**Built:** both paths in `app.py`'s `analyze()` resolve to the same
dataframe + schema + `run_pipeline()` call and the same
`render_template("results.html", ...)` -- the only difference is where
the dataframe and schema come from (bundled file + declared schema for
samples, upload stream + full inference for a real file). `run_store.py`
provides the "per-request location" from SCORE-6's criteria now, in a
basic form (UUID-keyed temp directory, no cleanup yet -- SCORE-6 remains
open specifically for TTL-based deletion). `templates/results.html`
renders the report as tables (no Chart.js yet -- that's SCORE-3) plus
working download links, which also meant building a basic version of
SCORE-4's download route (`/download/<run_id>/<artifact>`, with a
path-traversal guard on `run_id` and 404 on an unknown artifact) --
SCORE-4 remains open for response-header/content-type hardening.
`rules/` was not touched.

**Verification:** the single highest-value test per
`TESTING_STRATEGY.md` now exists and passes --
`test_messy_sample_report_matches_the_injected_ground_truth_exactly` in
`tests/test_analyze_pipeline.py` asserts the live `/analyze` → `/download`
round trip produces the *exact* counts from `samples/injected_counts.json`
(4 missing phones, 4 invalid emails, 5 duplicates, 4 auto-corrected
names), not just "some errors." Also covers: clean sample shows zero
problems everywhere, a real (non-sample) upload reaches the same
pipeline, download serves real content, and three rejection cases
(invalid run_id, path-traversal attempt in run_id, unrecognized artifact
name) all 404 cleanly. Full suite: 87/87 passing. Manually reconfirmed
against the real dev server -- `65 rows analyzed, 52 clean, 13 flagged,
5 duplicate rows`, matching every number verified by hand back in Phase 3.

---

### SCORE-3 — Results page with Chart.js rendering
**Type:** Feature | **Priority:** P0 | **Status: Done (2026-11-09)**

**Description:** Renders the four-rule report as stat cards plus the
charts, client-side, per the original design decision (Chart.js over CDN,
no server-side image generation -- see the project's earlier planning
notes on why `matplotlib`-style `plt.savefig()` was deliberately *not*
chosen for this engine, unlike `etl/`'s charts).

**Acceptance Criteria:**
- One stat card per rule (Completeness, Validity, Uniqueness, Consistency).
- At least one Chart.js visualization of the per-column breakdown.
- Page works whether the run came from a sample or a real upload.

**Built:** `report_summary.py` -- `build_summary()` (one headline number
per rule) and `build_chart_data()` (per-column Missing%/Invalid% arrays,
aligned on Completeness's column list since that's the one rule
guaranteed to cover every column). Four stat cards in `results.html`,
plus two Chart.js charts: an overview doughnut (clean vs. flagged) and a
grouped bar chart of the per-column breakdown. Chart data is embedded as
a JSON `<script type="application/json">` block and parsed client-side,
not inlined directly into a JS statement (avoids any risk of a value
containing `</script>`-like content breaking the page). Both canned
samples and a real upload render correctly through the same template.

**Verification:** `tests/test_report_summary.py` includes a direct
cross-check against the real messy sample's report, matching
`samples/injected_counts.json` exactly. `tests/test_results_charts.py`
checks Chart.js is actually loaded, both canvases exist, the stat-card
numbers are exactly `98.97%` / `4` / `7.69%` / `4` for the messy sample
(computed by hand, not guessed), the chart-data blob's per-column values
match ground truth, the clean sample's chart data is all zero, and the
page works for a real (non-sample) upload too. Full suite: 97/97 passing.
Visually reconfirmed against the real dev server. Note: this tier proves
the data feeding the charts is exactly correct; it cannot prove the
canvas actually paints pixels correctly in a browser -- that's
Playwright's job, intentionally not built yet per `TESTING_STRATEGY.md`'s
tier ordering.

---

### SCORE-4 — Artifact download routes
**Type:** Feature | **Priority:** P1 | **Status: Basic version done via SCORE-2; hardening still open**

**Description:** `GET /download/<run_id>/<artifact>` for `clean.csv`,
`garbage.csv`, and `report.json`.

**Acceptance Criteria:**
- Each artifact downloads with a sensible filename and correct
  `Content-Type`.
- Requesting an artifact for a `run_id` that doesn't exist (expired,
  invalid, or someone guessing) returns 404, not a server error.

**What SCORE-2 already built:** the route exists, works, and 404s
correctly on an invalid/path-traversal `run_id` or an unrecognized
artifact name (tested in `tests/test_analyze_pipeline.py`). **Still
open:** explicit `Content-Type`/`Content-Disposition` correctness per
artifact (currently relying on `send_file`'s defaults rather than
setting them deliberately), and whatever SCORE-6's cleanup does to a
`run_id` that *used to* exist.

---

## Epic: SCORE-SAFE — Upload Safety

### SCORE-5 — Server-side upload guards
**Type:** Security | **Priority:** P0 | **Status: Done (2026-11-09)**

**Description:** The caps already specified in `scoremark_project.md`
(2MB file size, 20,000 row max, 50 column max), enforced in Flask before
`run_pipeline()` ever sees the file -- not just suggested by client-side JS.

**Acceptance Criteria:**
- Oversized/too-wide/too-long files are rejected with a clear message,
  not a stack trace or a slow timeout.
- Extension *and* content-sniffed type are both checked (same principle
  as `rules/io.py`'s delimiter detection -- never trust a label alone).

**Built:** `upload_guards.py` -- `validate_filename` (extension),
`validate_file_size` (exact 2MB cap), `validate_is_text_content`
(null-byte check -- the "content, not just extension" half),
`validate_dataframe_shape` (row/column caps, checked after the real
parse via `rules/io.read_csv_as_text()`, which doubles as the deepest
content check: a file that isn't genuinely CSV-shaped fails there with a
clear `CsvStructureError`, not a guess). Wired into `/analyze` in
`app.py`, ahead of SCORE-2 as planned -- a passing file still only gets
a stub acknowledgment, not real processing. `app.config["MAX_CONTENT_LENGTH"]`
set as the outer Werkzeug-level net (with headroom for multipart
overhead), with a custom `413` handler so an over-limit request gets a
clear message instead of Flask's default error page. Canned samples
skip all of this by design -- never attacker-controlled bytes.

13 unit tests (`tests/test_upload_guards.py`) + 7 integration tests
through the real endpoint (`tests/test_web_routes.py`) -- every guard
has both a unit test proving the function is correct in isolation and an
integration test proving it's actually wired in, including the 413 path
specifically (a different mechanism than the 400s the other guards
return). Full suite: 79/79 passing. Also manually confirmed against the
real running dev server (`python app.py` + `curl`), not just the test
client.

---

### SCORE-6 — Per-request artifact storage with cleanup
**Type:** Chore | **Priority:** P1 | **Status: Basic storage done via SCORE-2; cleanup still open**

**Description:** Resolves the open question in `ARCHITECTURE_HANDOFF.md`
-- where do `clean.csv`/`garbage.csv`/`report.json` live between the
`POST /analyze` that creates them and the `GET /download/...` calls that
serve them.

**Acceptance Criteria:**
- Each run gets an isolated temp directory, not a shared/global path
  (two concurrent visitors must never see each other's data).
- A cleanup strategy exists (TTL-based deletion, or cleared on next
  process start) appropriate for PythonAnywhere's free-tier disk quota.

**What SCORE-2 already built:** `run_store.py` -- UUID-keyed temp
directory per run, satisfying the isolation criterion. **Still open:**
nothing deletes old run directories yet; this ticket is specifically the
cleanup half.

---

### SCORE-7 — Client-side size check (UX only, not the real guard)
**Type:** Feature | **Priority:** P2

**Description:** Immediate feedback on file selection, before any upload
starts. Explicitly not a substitute for SCORE-5.

**Acceptance Criteria:**
- A file exceeding the cap is flagged in the browser before the form
  submits.
- Removing/bypassing this check (e.g. via dev tools) still results in a
  correct server-side rejection (SCORE-5), not an error.

---

### SCORE-8 — Basic rate limiting on `/analyze`
**Type:** Security | **Priority:** P1 | **Status: Done (2026-11-09)**

**Description:** Per-IP request cap, as specified in
`scoremark_project.md`'s abuse-guard section. `Flask-Limiter` is not yet
in `requirements.txt`.

**Acceptance Criteria:**
- `Flask-Limiter` added to `requirements.txt`.
- A reasonable per-IP limit applied to `/analyze` specifically (canned
  samples can stay unlimited or have a much higher cap, since they carry
  no processing-cost risk from attacker-controlled input).

**Built:** `Flask-Limiter==4.1.1` added to `requirements.txt`. `app.py`
wires up a module-level `Limiter(get_remote_address, app=app,
storage_uri="memory://")` -- per-IP, in-memory, which is the right fit
for PythonAnywhere's free tier (a single always-on process, not
auto-scaled; see the comment in `app.py` next to `limiter`'s
definition). `/analyze` carries `@limiter.limit("10 per minute;100 per
day")`, two windows so a slow trickle can't quietly add up to more than
the per-minute number suggests on its own. Canned samples are exempt via
`exempt_when=_is_sample_request` (checks `request.form.get("sample") in
SAMPLE_FILES`) rather than splitting into two routes, keeping SCORE-2's
"no duplicated logic between the sample and upload paths" property
intact. A custom `429` handler returns a plain "Too many requests.
Please wait a moment and try again." message instead of Flask's default
error page.

**A real risk found before writing any test:** Flask-Limiter's in-memory
counter lives on the shared `limiter` object for the whole pytest
process, not per-test. Left alone, the dozen-plus pre-existing tests
that already POST to `/analyze` (across `test_web_routes.py`,
`test_analyze_pipeline.py`, `test_results_charts.py`) would eventually
trip the 10-per-minute limit and fail with unrelated 429s. Fixed with
`tests/conftest.py` -- an `autouse=True` fixture that calls
`limiter.reset()` before every single test in the suite, not just the
new rate-limiting ones.

**Verification:** `tests/test_rate_limiting.py` adds two tests --
10 real uploads in a row return 200 and an 11th returns 429 with the
expected message; and with the upload limit exhausted, both
`sample=clean` and `sample=messy` still return 200. Full suite: 99/99
passing (confirming the `conftest.py` reset fixture actually prevents
the pre-existing tests from breaking on shared rate-limit state, which
was the specific risk identified above). Also manually reconfirmed
against the real running dev server (`python app.py` + `curl.exe`):
10 uploads return `200`, the 11th returns `429` with the exact
"Too many requests..." body; with the limit still exhausted,
`sample=clean` and `sample=messy` both return `200`; and a further
upload attempt immediately afterward still correctly returns `429`
(proving the samples path truly doesn't touch the upload counter).

---

## Epic: SCORE-DEPLOY — Deployment

### SCORE-9 — Deploy to PythonAnywhere
**Type:** Chore | **Priority:** P0

**Description:** The concrete steps already written out in earlier
planning (console-based `git clone`, virtualenv, manual WSGI config,
Reload) -- this ticket is "actually do it," not "figure out how."

**Acceptance Criteria:**
- `yourname.pythonanywhere.com` serves the real app, not the Phase 2
  scaffold placeholder text.
- `php -l`-equivalent sanity check for Python: `python -m py_compile` (or
  just importing `app`) run clean before deploying.

---

### SCORE-10 — Add Scoremark to the portfolio's Projects CMS
**Type:** Feature | **Priority:** P1

**Description:** One entry, added through `/projects/create` (the
feature we already built and smoke-tested) -- title, description, the
PythonAnywhere URL as the link, GitHub repo referenced in the
description/tags.

**Acceptance Criteria:**
- Entry appears on the public `/projects` page.
- Link is live and correct at the time the entry is published.

---

### SCORE-11 — Push `rules/` + the new web app to its own GitHub repo
**Type:** Chore | **Priority:** P1

**Description:** Same ownership convention as Cartana -- own repo under
`mayerz6`, excluded from the portfolio's own git history (already
gitignored via `public/dev-projects/*`).

**Acceptance Criteria:**
- Repo exists, README covers the four rules precisely (reuse
  `scoremark_project.md`'s definitions), links the live demo.
- `etl/` is explicitly **not** included in this repo (see SCORE-12).

---

### SCORE-12 — Push `etl/` to its own, separate GitHub repo
**Type:** Chore | **Priority:** P2

**Description:** The fixed-schema/hybrid ETL tool, kept as its own
project per the architecture decision -- never imported by the web app,
never in the same repo as `rules/`.

**Acceptance Criteria:**
- Repo exists, `handoff.md` and `docs/FIXED_SCHEMA_ETL_TUTORIAL.md` are
  its README/docs.
- No import from `rules/` anywhere in `etl/` (already true -- confirm it
  stays that way).

---

## Priority Summary

| Priority | Tickets |
|---|---|
| P0 | SCORE-1 ✅, SCORE-2 ✅, SCORE-3 ✅, SCORE-5 ✅, SCORE-9 |
| P1 | SCORE-4, SCORE-6, SCORE-8 ✅, SCORE-10, SCORE-11 |
| P2 | SCORE-7, SCORE-12 |

Recommended order: SCORE-1 → SCORE-5 → SCORE-2 → SCORE-6 → SCORE-3 →
SCORE-4 → SCORE-8 → SCORE-9 → SCORE-10/11, with SCORE-7 and SCORE-12
whenever convenient. Safety (SCORE-5) is sequenced before the real upload
path (SCORE-2) is wired up, not after -- the same lesson as the main
portfolio's own backlog: an auth/safety gap found after the feature works
is harder to retrofit than one designed in from the start.
