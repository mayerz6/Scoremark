
from dataclasses import dataclass
from typing import Dict, Tuple, List, Optional

@dataclass(frozen=True)
class DatasetSchema:
    header: tuple[str, ...]
    field_indices: dict[str, int]
    max_name_chars: int = 32
    max_field_bytes: int = 32
    has_header: bool = False

    @property
    def required_min_columns(self):
        return max(self.field_indices.values()) + 1
    
    
    # @property
    # def required_min_columns(self) -> int:
    #     return 11  # Minimum columns required for valid data (firstname, lastname, email, phone, address, city, state, zip, password, ip)