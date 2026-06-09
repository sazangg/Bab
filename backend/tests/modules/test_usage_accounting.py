from app.modules.usage.accounting import (
    unknown_usage,
    usage_from_provider_response,
    usage_from_stream_chunks,
)


def test_usage_from_provider_response_uses_reported_usage() -> None:
    usage = usage_from_provider_response(
        request_messages=[{"role": "user", "content": "Hello"}],
        response_body={
            "choices": [{"message": {"content": "Hi"}}],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
            },
        },
    )

    assert usage.prompt_tokens == 3
    assert usage.completion_tokens == 2
    assert usage.total_tokens == 5
    assert usage.usage_source == "provider_reported"


def test_openai_compatible_non_streaming_usage_is_provider_reported() -> None:
    usage = usage_from_provider_response(
        request_messages=[{"role": "user", "content": "Count this"}],
        response_body={
            "id": "chatcmpl-test",
            "choices": [{"message": {"content": "Done"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        },
    )

    assert usage.prompt_tokens == 11
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 18
    assert usage.usage_source == "provider_reported"


def test_anthropic_style_usage_maps_input_and_output_tokens() -> None:
    usage = usage_from_provider_response(
        request_messages=[{"role": "user", "content": "Hello"}],
        response_body={
            "type": "message",
            "content": [{"type": "text", "text": "Hi"}],
            "usage": {"input_tokens": 8, "output_tokens": 3},
        },
    )

    assert usage.prompt_tokens == 8
    assert usage.completion_tokens == 3
    assert usage.total_tokens == 11
    assert usage.usage_source == "provider_reported"


def test_usage_from_provider_response_estimates_when_usage_is_missing() -> None:
    usage = usage_from_provider_response(
        request_messages=[{"role": "user", "content": "Hello there"}],
        response_body={"choices": [{"message": {"content": "General Kenobi"}}]},
    )

    assert usage.prompt_tokens is not None
    assert usage.prompt_tokens > 0
    assert usage.completion_tokens is not None
    assert usage.completion_tokens > 0
    assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
    assert usage.usage_source == "estimated"


def test_streaming_usage_estimates_when_provider_usage_is_absent() -> None:
    usage = usage_from_stream_chunks(
        request_messages=[{"role": "user", "content": "Say hello"}],
        chunks=[
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            b"data: [DONE]\n\n",
        ],
    )

    assert usage.prompt_tokens is not None
    assert usage.prompt_tokens > 0
    assert usage.completion_tokens is not None
    assert usage.completion_tokens > 0
    assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
    assert usage.usage_source == "estimated"


def test_unknown_usage_has_no_token_counts() -> None:
    usage = unknown_usage()

    assert usage.prompt_tokens is None
    assert usage.completion_tokens is None
    assert usage.total_tokens is None
    assert usage.usage_source == "unknown"
