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
    assert metadata.modality == "text+vision"
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
