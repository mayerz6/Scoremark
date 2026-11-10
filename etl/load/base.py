from abc import ABC, abstractmethod
from typing import Iterable, Dict, Any


class Loader(ABC):
    @abstractmethod
    def load(self, records: Iterable[Dict[str, Any]]):
        """Persist standardized records."""
        pass