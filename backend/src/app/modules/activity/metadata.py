from collections.abc import Mapping
from typing import Any

SECRET_FIELD_NAMES = {
    "api_key",
    "apikey",
    "key",
    "token",
    "secret",
    "password",
    "passwd",
    "pwd",
    "authorization",
    "bearer",
    "credential",
}
# Value prefixes that mark a string as secret-bearing regardless of its key name.
SECRET_VALUE_PREFIXES = ("sk-", "bab-sk-", "bearer ")
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
    if _is_secret_value(value):
        return REDACTED_VALUE
    return value


def _is_secret_field(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized.endswith("_id"):
        # Keep plain entity-id keys (provider_id, virtual_key_id) queryable, but do not
        # let an "_id" suffix shield a genuine secret root (secret_id, token_id, api_key_id).
        root = normalized[:-3].rstrip("_")
        return root in SECRET_FIELD_NAMES or any(
            part in SECRET_FIELD_NAMES for part in root.split("_")
        )
    return normalized in SECRET_FIELD_NAMES or any(
        part in SECRET_FIELD_NAMES for part in normalized.split("_")
    )


def _is_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(lowered.startswith(prefix) for prefix in SECRET_VALUE_PREFIXES)
