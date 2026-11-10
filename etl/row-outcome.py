@dataclass(frozen=True)
class RowOutcome:

    is_valid: bool = False
    processed: Optional[List[str]] = None
    reason: Optional[str] = None
    
    def __init__(self, row_data: dict, is_valid: bool, error_message: str = None):
        self.row_data = row_data
        self.is_valid = is_valid
        self.error_message = error_message
