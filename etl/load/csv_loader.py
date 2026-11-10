import csv
import os
from typing import Iterable, Dict, Any
from .base import Loader


class CSVLoader(Loader):

    def __init__(self, output_path: str, header, encoding="utf-8"):
        self.output_path = output_path
        self.header = header
        self.encoding = encoding

    def load(self, records):
        
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        with open(self.output_path, "w", newline="", encoding=self.encoding) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=self.header,
                extrasaction="ignore"
            )

            writer.writeheader()

            for record in records:
                writer.writerow(record)


class GarbageLoader:

    def __init__(self, output_path):
        self.output_path = output_path

    def load(self, records):
        
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        with open(self.output_path, "w", newline="", encoding="utf-8") as f:

            writer = csv.writer(f)

            for r in records:
                writer.writerow(r)