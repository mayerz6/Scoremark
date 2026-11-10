import csv
from typing import Iterable, Dict, Any, List
from .base import Extractor
from etl.schema import DatasetSchema
from etl.utils.encoding import detect_encoding


class CSVExtractor(Extractor):
    # def __init__(self, file_path: str, schema: DatasetSchema, delimiter: str = ",", encoding=None):
    def __init__(self, file_path: str, schema: DatasetSchema, delimiter: str = ",", encoding: str | None = None):
        self.file_path = file_path
        self.schema = schema
        self.delimiter = delimiter
        # self.encoding = encoding
        if encoding:
            self.encoding = encoding
        else:
            self.encoding = detect_encoding(file_path)



    def extract(self) -> Iterable[List[str]]:

        with open(self.file_path, encoding=self.encoding, newline="") as f:

            reader = csv.reader(f, delimiter=self.delimiter)
            header_pending = self.schema.has_header

            for row in reader:

                # Skip banner / garbage rows
                if len(row) < self.schema.required_min_columns:
                    continue

                # The first full-width row of a file with a header IS the
                # header -- never data. Yielding it sent the raw header to
                # stage 1's garbage file, and (worse) copied stage 2's
                # header into the final file as a data row, because stage 2
                # has no validation rule to reject it.
                if header_pending:
                    header_pending = False
                    continue

                yield row