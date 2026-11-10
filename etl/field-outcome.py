# ----------------------------
# Helpers / Transformers / Validators
# ----------------------------
class FieldOps:
    @staticmethod
    def clean_field(value: Optional[str]) -> str:
        return re.sub(r'[",\']', "", value).strip() if value else ""

    @staticmethod
    def to_camel_case(s: Optional[str]) -> Optional[str]:
        return None if s is None else " ".join(word.capitalize() for word in s.split())

    @staticmethod
    def validate_email(email: Optional[str]) -> bool:
        return bool(email and re.fullmatch(EMAIL_PATTERN, email.strip().lower()))

    @staticmethod
    def truncate_to_max_bytes(value: str, max_bytes: int, encoding: str = "utf-8") -> str:
        if not value:
            return ""
        encoded = value.encode(encoding, errors="ignore")
        if len(encoded) <= max_bytes:
            return value
        truncated = encoded[:max_bytes]
        while truncated:
            try:
                return truncated.decode(encoding)
            except UnicodeDecodeError:
                truncated = truncated[:-1]
        return ""

    @staticmethod
    def digits_only(value: str) -> str:
        return re.sub(r"\D+", "", value or "")
    
    @staticmethod
    def is_blank(value: Optional[str]) -> bool:
        return value is None or value.strip() == ""

