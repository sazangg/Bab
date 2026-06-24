from collections.abc import Mapping, Sequence
from typing import Any

REDACTED_VALUE = "[redacted]"

METRIC_KEYS = {
    "completion_tokens",
    "cost_cents",
    "cost_micro_cents",
    "prompt_tokens",
    "total_tokens",
}

SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "body",
    "content",
    "credential",
    "key_hash",
    "matched_text",
    "matched_values",
    "message",
    "password",
    "prompt",
    "raw_body",
    "raw_key",
    "request_body",
    "response",
    "secret",
    "token",
}


def redact_trace_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                redacted[key_text] = REDACTED_VALUE
            else:
                redacted[key_text] = redact_trace_value(item)
        return redacted
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [redact_trace_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in METRIC_KEYS:
        return False
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)
