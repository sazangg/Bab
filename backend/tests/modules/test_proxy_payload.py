from app.modules.gateway.provider_execution import normalize_provider_extra_body


def test_normalize_provider_extra_body_translates_max_tokens_for_gpt_5() -> None:
    normalized = normalize_provider_extra_body(
        extra_body={"max_tokens": 50, "temperature": 0},
        provider_model="gpt-5-mini",
    )

    assert normalized == {"max_completion_tokens": 50, "temperature": 0}


def test_normalize_provider_extra_body_preserves_max_tokens_for_legacy_models() -> None:
    normalized = normalize_provider_extra_body(
        extra_body={"max_tokens": 50},
        provider_model="gpt-4.1-mini",
    )

    assert normalized == {"max_tokens": 50}


def test_normalize_provider_extra_body_does_not_override_explicit_max_completion_tokens() -> None:
    normalized = normalize_provider_extra_body(
        extra_body={"max_tokens": 50, "max_completion_tokens": 25},
        provider_model="o3-mini",
    )

    assert normalized == {"max_tokens": 50, "max_completion_tokens": 25}
