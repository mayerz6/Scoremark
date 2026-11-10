"""
Loads a dataset's hand-maintained output headers:
datasets/<dataset>/confirmed_dataset_headers.py -> its `final_schema`.

Only `final_schema.header` is taken from the file. That tuple is the one
thing a person edits per dataset: which fields to extract, and in what
order they appear in the output. Everything else is derived from it, so
the file can't drift out of sync with itself:

  - field_indices: column position == position in `header`, because the
    stage-1 loader writes the processed file in exactly that order.
  - has_header: always True -- the stage-1 loader always writes one.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from .schema import DatasetSchema

HEADERS_FILE_NAME = "confirmed_dataset_headers.py"


class DatasetHeadersError(RuntimeError):
    pass


def load_final_schema(dataset_dir: str | Path) -> DatasetSchema:
    path = Path(dataset_dir) / HEADERS_FILE_NAME
    if not path.is_file():
        raise DatasetHeadersError(
            f"No {HEADERS_FILE_NAME} in {dataset_dir} -- create one with a `final_schema` "
            "whose `header` lists the fields to extract for this dataset."
        )

    spec = importlib.util.spec_from_file_location(f"_dataset_headers_{abs(hash(str(path)))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    declared = getattr(module, "final_schema", None)
    header = tuple(getattr(declared, "header", ()) or ())
    if not header:
        raise DatasetHeadersError(f"{path} must define `final_schema` with a non-empty `header`.")
    if len(set(header)) != len(header):
        raise DatasetHeadersError(f"{path}: `final_schema.header` lists a field more than once: {header}")

    return DatasetSchema(
        header=header,
        field_indices={field: i for i, field in enumerate(header)},
        has_header=True,
    )
