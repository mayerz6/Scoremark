
@dataclass
class DataQualityScorecard:
    file_name: str
    started_at: str
    finished_at: str

    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0

    # Why invalid?
    invalid_reasons: Dict[str, int] = None

    # Field-level
    null_or_blank_by_field: Dict[str, int] = None
    max_len_violations: Dict[str, int] = None
    email_invalid_count: int = 0
    phone_non_numeric_count: int = 0
    structural_bad_column_count: int = 0

    # Simple profiling
    top_email_domains: Dict[str, int] = None

    def __post_init__(self):
        self.invalid_reasons = self.invalid_reasons or {}
        self.null_or_blank_by_field = self.null_or_blank_by_field or {}
        self.max_len_violations = self.max_len_violations or {}
        self.top_email_domains = self.top_email_domains or {}

    def bump_reason(self, reason: str):
        self.invalid_reasons[reason] = self.invalid_reasons.get(reason, 0) + 1

    def bump_blank(self, field: str):
        self.null_or_blank_by_field[field] = self.null_or_blank_by_field.get(field, 0) + 1

    def bump_maxlen(self, field: str):
        self.max_len_violations[field] = self.max_len_violations.get(field, 0) + 1

    def bump_domain(self, email: str):
        # safe parsing after validation
        domain = email.split("@", 1)[1].lower()
        self.top_email_domains[domain] = self.top_email_domains.get(domain, 0) + 1
