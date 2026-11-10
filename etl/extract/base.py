from abc import ABC, abstractmethod
from typing import Iterable, List


class Extractor(ABC):
    @abstractmethod
    def extract(self) -> Iterable[List[str]]:
        """Return raw records as plain lists of string fields, in file column
        order -- nothing has mapped them onto named fields yet (that's the
        Transformer's job, using a DatasetSchema's field_indices)."""
        pass