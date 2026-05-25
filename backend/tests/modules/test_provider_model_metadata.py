from uuid import uuid4

from app.modules.providers.internal.model_metadata import (
    OpenAIModelMetadataAdapter,
    default_model_metadata_registry,
)
from app.modules.providers.internal.models import Provider


def test_openai_model_metadata_adapter_enriches_known_models() -> None:
    provider = Provider(
        id=uuid4(),
        org_id=uuid4(),
        name="OpenAI",
        slug="openai",
        base_url="https://api.openai.com/v1",
    )

    metadata = default_model_metadata_registry.get(
        provider=provider,
        provider_model_name="gpt-5.4",
    )

    assert metadata is not None
    assert metadata.context_window == 1_000_000
    assert metadata.input_modalities == ["text", "vision"]
    assert metadata.output_modalities == ["text"]
    assert metadata.capabilities["streaming"] is True
    assert metadata.capabilities["tools"] is True
    assert metadata.pricing.input_price_per_million_tokens is None


def test_openai_model_metadata_adapter_leaves_unknown_models_unenriched() -> None:
    provider = Provider(
        id=uuid4(),
        org_id=uuid4(),
        name="OpenAI",
        slug="openai",
        base_url="https://api.openai.com/v1",
    )

    metadata = default_model_metadata_registry.get(
        provider=provider,
        provider_model_name="unknown-openai-compatible-model",
    )

    assert metadata is None


def test_openai_model_metadata_adapter_can_match_by_base_url() -> None:
    provider = Provider(
        id=uuid4(),
        org_id=uuid4(),
        name="Custom OpenAI Proxy",
        slug="custom-openai-proxy",
        base_url="https://api.openai.com/v1",
    )

    assert OpenAIModelMetadataAdapter().supports(provider) is True


def test_provider_specific_metadata_uses_provider_pricing() -> None:
    mistral = Provider(
        id=uuid4(),
        org_id=uuid4(),
        name="Mistral AI",
        slug="mistral",
        base_url="https://api.mistral.ai/v1",
    )
    groq = Provider(
        id=uuid4(),
        org_id=uuid4(),
        name="Groq",
        slug="groq",
        base_url="https://api.groq.com/openai/v1",
    )

    mistral_metadata = default_model_metadata_registry.get(
        provider=mistral,
        provider_model_name="mistral-small-latest",
    )
    groq_metadata = default_model_metadata_registry.get(
        provider=groq,
        provider_model_name="llama-3.3-70b-versatile",
    )

    assert mistral_metadata is not None
    assert mistral_metadata.pricing.input_price_per_million_tokens == 10
    assert mistral_metadata.pricing.output_price_per_million_tokens == 30
    assert groq_metadata is not None
    assert groq_metadata.pricing.input_price_per_million_tokens == 59
    assert groq_metadata.pricing.output_price_per_million_tokens == 79
