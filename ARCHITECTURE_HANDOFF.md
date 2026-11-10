# Scoremark — Web Architecture Handoff

Last updated: 2026-11-09

## Purpose

This is the deployment/architecture decision record for turning Scoremark
into something a visitor can actually use from `larrymayers.site`. It's
separate from the other two docs in this folder on purpose:

- `scoremark_project.md` — the *rules engine's* technical spec (what
  Completeness/Validity/Uniqueness/Consistency mean, their output
  contracts). Doesn't describe hosting or routing.
- `handoff.md` — the *fixed-schema ETL tool's* (`etl/`) bug-journey and
  hybrid-detector history. A CLI tool, not a web app, and not the thing
  this document is about.

This file is about the third piece: how a browser, a PHP page on
Hostinger, and a Python process end up connected into one working product.

For how we verify any of this actually works, see `TESTING_STRATEGY.md`
-- a deliberately separate document, same reasoning as the main
portfolio keeping `TESTING_CICD_STRATEGY.md` apart from
`PROJECT_HANDOFF.md`: architecture answers "how is this built," testing
strategy answers "how do we know it still works," and conflating the two
makes both harder to find later.

## The decision: two engines, one of them never goes near the web

Two Python codebases exist in this repo, and they are **not**
interchangeable for a public upload form:

| | `rules/` | `etl/` |
|---|---|---|
| Built for | an arbitrary stranger's CSV | a specific 8-field customer/order record set |
| Schema handling | content-inferred, any columns | content+header detected, but only for firstname/lastname/email/phone/address/city/zipcode/ip_address |
| Abuse guards | specified in `scoremark_project.md` (size/row/column caps) | none -- it's a CLI tool run by hand against known files |
| Status | 4 rules + clean/garbage split, tested | dedup + independent validation + provenance + charts, tested |

**Decision: `rules/` powers the public web tool. `etl/` stays a separate,
CLI-driven batch tool with its own GitHub repo, and is never imported by
the web app.** This isn't just the safer technical choice (`etl/`'s
hybrid detector would mostly return `unresolved` on an unrelated file
shape) -- it's also what makes "frontend work can't affect the ETL
pipeline's core services" true by construction: if `etl/` is never
imported by anything web-facing, nothing built for the web can touch it.

## The decision: no PHP relay

**Rejected design:** browser uploads to a PHP page on Hostinger → PHP
relays the file to a Python server → Python processes it → PHP renders
the result.

**Why rejected:**
- Hostinger's PHP execution time limit (commonly 30-60s, plan-dependent)
  now also has to cover the network round-trip to Python and back. A slow
  hop risks PHP timing out before Python even finishes -- a failure mode
  that doesn't exist if the browser talks to Python directly.
- File-size limits would need to stay consistent across three places (the
  HTML form, PHP's `upload_max_filesize`/`post_max_size`, Flask's own
  cap) instead of one.
- It provides no actual security benefit. The Python endpoint still has
  to be publicly reachable for PHP to call it, so nothing stops a visitor
  from calling it directly and skipping PHP entirely. The relay would be
  branding, not a gate.

**Chosen design:** the Flask app serves its own complete page -- its own
upload form, its own results view, its own file-download routes. PHP's
only involvement is a card in the portfolio's Projects CMS linking out to
it, exactly like Cartana. No file ever touches PHP.

**Known, unavoidable cost of this choice:** PythonAnywhere's free tier
does not support custom domains (confirmed against
[help.pythonanywhere.com](https://help.pythonanywhere.com/pages/CustomDomains)
before relying on it, not assumed) -- so visiting the live tool means
leaving `larrymayers.site` for `yourname.pythonanywhere.com`. Solvable
only by a paid PythonAnywhere plan or a different host, not by any amount
of clever routing on the PHP side.

## The resulting architecture

```
Browser
   |
   |  GET /                      -> upload form + canned-sample buttons
   |  POST /analyze (multipart)  -> runs rules/disposition.run_pipeline()
   |  GET /download/<artifact>   -> clean.csv / garbage.csv / report.json
   v
Flask app (yourname.pythonanywhere.com)
   |
   |  imports rules/ as a library -- no subprocess, no HTTP hop, no
   |  relay. Same process, same request.
   v
rules/ (completeness.py, validity.py, uniqueness.py, consistency.py,
        disposition.py, schema.py, io.py)
```

```
larrymayers.site (Hostinger, PHP)
   |
   |  Projects CMS entry: title, description, link = the PythonAnywhere URL,
   |  GitHub repo link in the description/tags
   v
   (visitor clicks through -- domain changes here, by design)
```

### What each layer actually does

- **Client-side JS (in the Flask-served page, not PHP):** a quick size
  check on file selection, purely for immediate feedback before any
  upload starts. Never the only check -- trivially bypassed (disabled
  JS, a raw request), so Flask enforces the same cap again server-side
  regardless. Belongs to the Flask app's own `static/` assets, not to
  anything PHP serves.
- **Flask routes:** `GET /` (form + sample buttons), `POST /analyze`
  (accepts either an uploaded file or a `?sample=` reference, calls
  `rules/disposition.run_pipeline()` directly as a Python import, renders
  the report + Chart.js charts), `GET /download/<run_id>/<artifact>`
  (serves the three output files).
- **`rules/` package:** untouched by any of this -- it's called the same
  way `analyze.py` already calls it. The web layer is a new caller of an
  existing, already-tested library, not a rewrite of it.
- **PHP / portfolio:** one Projects CMS entry. Nothing else changes on
  the Hostinger side.

## What's still an open question, not yet decided

- **Run identity / artifact lifetime.** Each `POST /analyze` needs a
  place to put its `clean.csv`/`garbage.csv`/`report.json` so the
  following `GET /download/...` calls can find them, and a reason to
  eventually delete them (PythonAnywhere's free disk quota is small).
  Simplest option: a per-request temp directory, deleted after some
  short TTL or on next server restart -- deliberately not a database,
  since nothing here needs to persist.
- **Concurrent uploads.** PythonAnywhere's free web app is single
  always-on process, not auto-scaled. Fine for a portfolio's traffic
  level; worth knowing it's not built for concurrent heavy load.
