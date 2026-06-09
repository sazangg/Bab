from collections.abc import Mapping
from typing import Any

SECRET_FIELD_NAMES = {
    "api_key",
    "key",
    "token",
    "secret",
    "password",
    "authorization",
}
REDACTED_VALUE = "[redacted]"


def sanitize_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_secret_field(key_text):
                sanitized[key_text] = REDACTED_VALUE
            else:
                sanitized[key_text] = sanitize_metadata(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_metadata(item) for item in value]
    return value


def _is_secret_field(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized.endswith("_id"):
        return False
    return normalized in SECRET_FIELD_NAMES or any(
        part in SECRET_FIELD_NAMES for part in normalized.split("_")
    )
