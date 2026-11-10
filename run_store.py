"""
Per-request artifact storage -- SCORE-2's minimal working version of what
SCORE-6 is specifically scoped to harden (TTL-based cleanup, appropriate
for PythonAnywhere's free-tier disk quota -- see ARCHITECTURE_HANDOFF.md's
open questions). This version works correctly and safely today; it just
never deletes anything yet.

Each run gets its own directory under a temp root, keyed by a random
run_id, so two concurrent visitors can never see or overwrite each
other's files.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path

import pandas as pd

_STORE_ROOT = Path(tempfile.gettempdir()) / "scoremark_runs"
_ALLOWED_ARTIFACTS = {"clean.csv", "garbage.csv", "report.json"}


def save_run(report: dict, clean_df: pd.DataFrame, garbage_df: pd.DataFrame) -> str:
    run_id = uuid.uuid4().hex  # lowercase hex only -- see artifact_path()'s traversal guard
    run_dir = _STORE_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    clean_df.to_csv(run_dir / "clean.csv", index=False)
    garbage_df.to_csv(run_dir / "garbage.csv", index=False)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))

    return run_id


def artifact_path(run_id: str, artifact: str) -> Path | None:
    """
    Returns the real file path for a (run_id, artifact) pair, or None if
    either one isn't valid -- callers should treat None as "404," not an
    error. The run_id check matters beyond input hygiene: run_id comes
    straight from the URL, and uuid4().hex is always 32 lowercase hex
    characters (so a legitimate run_id always passes) -- rejecting anything
    else is what stops a crafted run_id like "../../etc" from ever being
    joined into a filesystem path.
    """
    if artifact not in _ALLOWED_ARTIFACTS:
        return None
    if not _is_valid_run_id(run_id):
        return None

    path = _STORE_ROOT / run_id / artifact
    return path if path.is_file() else None


def delete_run(run_id: str) -> bool:
    """
    Permanently deletes every artifact of one run -- the visitor-initiated
    "delete my data" action. The original upload is never written to disk
    (app.py parses it in memory), so clean.csv, garbage.csv and report.json
    are the only copies of the visitor's data this app holds; removing the
    run's directory removes all of it.

    Returns True if something was deleted, False if the run_id is invalid
    or already gone -- either way, nothing of that run remains.
    """
    if not _is_valid_run_id(run_id):
        return False
    run_dir = _STORE_ROOT / run_id
    if not run_dir.is_dir():
        return False
    shutil.rmtree(run_dir)
    return True


def _is_valid_run_id(run_id: str) -> bool:
    # Exactly what uuid4().hex produces: 32 lowercase hex characters. Stricter
    # than str.isalnum(), which also accepts non-ASCII letters and digits.
    # Either way, nothing like "../../etc" can ever reach a filesystem path.
    return len(run_id) == 32 and all(c in "0123456789abcdef" for c in run_id)
