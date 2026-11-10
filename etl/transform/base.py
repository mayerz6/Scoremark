from abc import ABC, abstractmethod
from typing import Dict, Any


class Transformer(ABC):
    @abstractmethod
    def transform(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Map raw record to standardized schema."""
        pass