"""
User-initiated deletion of a batch run's data artifacts, once its reports
exist -- so the person running the ETL decides what's kept at the end.

Never touched, under any option:
  - the raw input files in records/ (the user's own source data), and
  - the reports: reports/*.png and batch/metadata/ingestion_report.json
    (counts, detected layouts and rule results -- no row data).
"""

from __future__ import annotations

from pathlib import Path

#: What each choice deletes. "intermediate" keeps only the deliverable.
SCOPES = ("all", "intermediate", "none")


def select_artifacts(artifacts: dict[str, list[str]], scope: str) -> list[str]:
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}, got {scope!r}")
    if scope == "none":
        return []
    selected = list(artifacts.get("intermediate", []))
    if scope == "all":
        selected += artifacts.get("final", [])
    return selected


def delete_artifacts(paths: list[str], allowed_root: Path) -> list[str]:
    """
    Deletes each file in `paths` that exists, then removes any folders left
    empty under `allowed_root`. Refuses any path outside `allowed_root` --
    a guard so a bug elsewhere can never turn this into deleting the raw
    records or anything else. Returns the paths actually deleted.
    """
    root = Path(allowed_root).resolve()
    deleted = []

    for path in paths:
        target = Path(path).resolve()
        if root not in target.parents:
            raise ValueError(f"Refusing to delete {target}: outside {root}")
        if target.is_file():
            target.unlink()
            deleted.append(str(path))

    for folder in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()

    return deleted


def ask_scope() -> str:
    """Interactive prompt; anything but an explicit choice keeps everything."""
    print(
        "\nReports are done. The ETL data artifacts (per-file outputs, garbage files,\n"
        "combined and deduplicated datasets) can now be deleted. Your raw files in\n"
        "records/ and the reports (charts + ingestion_report.json) are always kept."
    )
    answer = input(
        "Delete artifacts? [a]ll / [i]ntermediate only (keep combined_deduplicated.csv) / [N]o: "
    ).strip().lower()
    return {"a": "all", "all": "all", "i": "intermediate", "intermediate": "intermediate"}.get(answer, "none")
