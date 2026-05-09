from typing import Any

from pydantic import BaseModel

ESTIMATED_CHARS_PER_TOKEN = 4


class UsageAccounting(BaseModel):
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    usage_source: str


def usage_from_provider_response(
    *,
    request_messages: list[dict[str, Any]],
    response_body: dict[str, Any] | None,
) -> UsageAccounting:
    reported = _extract_provider_usage(response_body)
    if reported is not None:
        return reported

    return _estimate_usage(request_messages=request_messages, response_body=response_body)


def unknown_usage() -> UsageAccounting:
    return UsageAccounting(
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        usage_source="unknown",
    )


def _extract_provider_usage(response_body: dict[str, Any] | None) -> UsageAccounting | None:
    if response_body is None:
        return None

    usage = response_body.get("usage")
    if not isinstance(usage, dict):
        return None

    prompt_tokens = _int_or_none(usage.get("prompt_tokens"))
    completion_tokens = _int_or_none(usage.get("completion_tokens"))
    total_tokens = _int_or_none(usage.get("total_tokens"))
    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None

    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    return UsageAccounting(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        usage_source="provider_reported",
    )


def _estimate_usage(
    *,
    request_messages: list[dict[str, Any]],
    response_body: dict[str, Any] | None,
) -> UsageAccounting:
    prompt_tokens = _estimate_tokens(_messages_text(request_messages))
    completion_tokens = _estimate_tokens(_assistant_text(response_body))
    return UsageAccounting(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        usage_source="estimated",
    )


def _messages_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        parts.append(_content_to_text(message.get("content")))
    return "\n".join(parts)


def _assistant_text(response_body: dict[str, Any] | None) -> str:
    if response_body is None:
        return ""
    choices = response_body.get("choices")
    if not isinstance(choices, list):
        return ""

    parts: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            parts.append(_content_to_text(message.get("content")))
    return "\n".join(parts)


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_content_part_to_text(part) for part in content)
    return str(content)


def _content_part_to_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        value = part.get("text")
        if isinstance(value, str):
            return value
    return ""


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / ESTIMATED_CHARS_PER_TOKEN))


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
