"""
Scoremark -- Flask web app.

SCORE-1: the upload + sample-selection form (this file + templates/index.html).
SCORE-5: server-side upload guards (upload_guards.py), wired in ahead of
SCORE-2 on purpose, so the real pipeline never had to be the thing that
first noticed a bad upload.
SCORE-2: this is where /analyze starts calling rules/disposition.run_pipeline()
for real. Both the canned-sample path and the upload path converge on the
exact same run_pipeline() call and the exact same rendering code below --
no separate "sample logic" and "upload logic," by design (see this
ticket's acceptance criteria in FRONTEND_BACKLOG.md).
"""

import io
from pathlib import Path

from flask import Flask, abort, render_template, request, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from analyze import SAMPLE_KEY_COLUMNS, SAMPLE_SCHEMA
from report_summary import build_chart_data, build_occupancy, build_summary
from rules.disposition import run_pipeline
from rules.io import CsvStructureError, decode_csv_bytes, read_csv_rows
from run_store import artifact_path, delete_run, save_run
from upload_guards import (
    FLASK_MAX_CONTENT_LENGTH,
    MAX_FILE_SIZE_BYTES,
    UploadRejected,
    validate_dataframe_shape,
    validate_file_size,
    validate_filename,
    validate_is_text_content,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = FLASK_MAX_CONTENT_LENGTH

SAMPLES_DIR = Path(__file__).parent / "samples"
SAMPLE_FILES = {"clean": "clean_sample.csv", "messy": "messy_sample.csv"}

#: Per-IP, in-memory storage is deliberately simple -- appropriate for a
#: single always-on process (see ARCHITECTURE_HANDOFF.md's "Concurrent
#: uploads" note: PythonAnywhere's free tier is exactly that, not
#: auto-scaled). Would need revisiting (e.g. a shared Redis store) only
#: if this ever ran as more than one process.
limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")

#: Generous enough for a legitimate visitor trying a few real files in a
#: sitting, strict enough to make rapid-fire abuse pointless. Two windows
#: (not just one) so a slow trickle of requests can't quietly run up a
#: much bigger total than the per-minute number suggests on its own.
ANALYZE_RATE_LIMIT = "10 per minute;100 per day"


def _is_sample_request() -> bool:
    # Canned samples carry no processing-cost risk from attacker-controlled
    # input (scoremark_project.md's Input section) -- they're exempt from
    # the limit below entirely, not just given a higher number.
    return request.form.get("sample") in SAMPLE_FILES


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
@limiter.limit(ANALYZE_RATE_LIMIT, exempt_when=_is_sample_request)
def analyze():
    sample = request.form.get("sample")
    uploaded_file = request.files.get("file")

    if sample in SAMPLE_FILES:
        # Bundled, zero-risk files -- never attacker-controlled bytes, so
        # none of the upload guards below apply to this branch. Declared
        # schema used here because we wrote these files ourselves and can
        # be precise, exactly as analyze.py already does for the CLI.
        source_name = SAMPLE_FILES[sample]
        read = read_csv_rows(SAMPLES_DIR / source_name)
        declared_schema, key_columns = SAMPLE_SCHEMA, SAMPLE_KEY_COLUMNS

    elif uploaded_file and uploaded_file.filename:
        source_name = uploaded_file.filename
        try:
            validate_filename(uploaded_file.filename)

            uploaded_file.stream.seek(0, io.SEEK_END)
            size_in_bytes = uploaded_file.stream.tell()
            uploaded_file.stream.seek(0)
            validate_file_size(size_in_bytes)

            raw_bytes = uploaded_file.stream.read()
            uploaded_file.stream.seek(0)
            # Decode first (BOM, UTF-8, Windows-1252), THEN check for binary
            # content -- see validate_is_text_content() for why the order matters.
            text, _encoding = decode_csv_bytes(raw_bytes)
            validate_is_text_content(text)

            read = read_csv_rows(io.StringIO(text), source_name=uploaded_file.filename)
            validate_dataframe_shape(read.total_rows, len(read.dataframe.columns))
        except (UploadRejected, CsvStructureError) as error:
            return str(error), 400

        # No declared schema for an arbitrary upload -- full content+header
        # inference, exactly as scoremark_project.md's "Schema Resolution"
        # section describes. Forcing the sample schema (or its "email" key)
        # onto an unrelated file would produce meaningless results, not an
        # error -- the same lesson learned the hard way with etl/'s hybrid
        # detector (see the other tool's handoff.md).
        declared_schema, key_columns = None, None

    else:
        return "No sample selected and no file uploaded.", 400

    dataframe = read.dataframe
    result = run_pipeline(
        dataframe,
        declared_schema=declared_schema,
        key_columns=key_columns,
        malformed_rows=read.malformed_rows,
    )
    run_id = save_run(result["report"], result["clean_df"], result["garbage_df"])

    return render_template(
        "results.html",
        report=result["report"],
        summary=build_summary(result["report"], len(dataframe)),
        chart_data=build_chart_data(result["report"]),
        occupancy=build_occupancy(result["report"]),
        run_id=run_id,
        source_name=source_name,
        total_count=read.total_rows,
        clean_count=len(result["clean_df"]),
        garbage_count=len(result["garbage_df"]),
    )


@app.route("/download/<run_id>/<artifact>")
def download(run_id, artifact):
    path = artifact_path(run_id, artifact)
    if path is None:
        abort(404)
    return send_file(path, as_attachment=True)


@app.route("/delete/<run_id>", methods=["POST"])
def delete(run_id):
    """
    Visitor-initiated deletion of everything this app stored for one run.
    POST only, so a link preview or crawler following a URL can never
    delete anything. The run_id is a 128-bit random value only the
    visitor's own results page knows -- the same capability that already
    guards the downloads.
    """
    deleted = delete_run(run_id)
    return render_template("deleted.html", deleted=deleted), (200 if deleted else 404)


@app.errorhandler(413)
def handle_request_too_large(_error):
    max_mb = MAX_FILE_SIZE_BYTES / 1024 / 1024
    return f"File is too large. Maximum allowed is {max_mb:.0f} MB.", 413


@app.errorhandler(429)
def handle_rate_limit_exceeded(_error):
    return "Too many requests. Please wait a moment and try again.", 429


if __name__ == "__main__":
    app.run(debug=True)
