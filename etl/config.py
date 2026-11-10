
from dataclasses import dataclass
from typing import Dict, Tuple, List, Optional

@dataclass(frozen=True)
class AppConfig:

    input_folder: str
    output_folder: str
    garbage_folder: str
    delimiter: str = ';'  # Default delimiter for CSV files
    input_encoding: str = 'latin-1'  # Default encoding for input files
    output_encoding: str = 'utf-8'  # Default encoding for output files    
    batch_size: int = 1000  # Default batch size for processing large files