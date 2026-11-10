"""
Where a dataset's charts go: next to the raw data they describe, never a
hardcoded location. One dataset's charts can then never overwrite
another's.

    datasets/<dataset>/records/<raw>.csv  ->  datasets/<dataset>/reports/

The raw file normally sits in a `records/` folder alongside its dataset's
other stage folders (to-be-ingested/, completed/, garbage/, metadata/), so
`reports/` goes beside those, in the dataset folder itself. A raw file
that isn't inside a `records/` folder gets a `reports/` folder right next
to it instead.
"""

from __future__ import annotations

from pathlib import Path

RAW_FOLDER_NAME = "records"
REPORTS_FOLDER_NAME = "reports"


def dataset_dir_for(raw_path: str | Path) -> Path:
    """
    The dataset folder a raw file (or a folder of raw files) belongs to:
    the parent of its `records/` folder, or the folder it sits in.
    """
    path = Path(raw_path)
    folder = path if path.is_dir() else path.parent
    if folder.name.lower() == RAW_FOLDER_NAME:
        folder = folder.parent
    return folder


def reports_dir_for(raw_path: str | Path) -> Path:
    """
    raw_path: a raw dataset file, or the folder that holds the raw files
    (main_folder_batch.py processes a whole folder at once).
    """
    return dataset_dir_for(raw_path) / REPORTS_FOLDER_NAME
