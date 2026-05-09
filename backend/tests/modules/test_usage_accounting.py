from app.modules.request_logs.usage import unknown_usage, usage_from_provider_response


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


def test_unknown_usage_has_no_token_counts() -> None:
    usage = unknown_usage()

    assert usage.prompt_tokens is None
    assert usage.completion_tokens is None
    assert usage.total_tokens is None
    assert usage.usage_source == "unknown"
