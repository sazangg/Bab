from dataclasses import dataclass, field
from typing import Protocol

from app.modules.providers.internal.models import Provider


@dataclass(frozen=True)
class ModelPricingMetadata:
    input_price_per_million_tokens: int | None = None
    output_price_per_million_tokens: int | None = None
    cached_input_price_per_million_tokens: int | None = None


@dataclass(frozen=True)
class ModelMetadata:
    provider_model_name: str
    version: str | None = None
    input_modalities: list[str] = field(default_factory=lambda: ["text"])
    output_modalities: list[str] = field(default_factory=lambda: ["text"])
    capabilities: dict[str, bool] = field(default_factory=dict)
    context_window: int | None = None
    pricing: ModelPricingMetadata = field(default_factory=ModelPricingMetadata)
    rate_limit_hints: dict = field(default_factory=dict)


class ProviderModelMetadataAdapter(Protocol):
    def supports(self, provider: Provider) -> bool: ...

    def get(self, provider_model_name: str) -> ModelMetadata | None: ...


class OpenAIModelMetadataAdapter:
    def supports(self, provider: Provider) -> bool:
        slug = provider.slug or ""
        return slug == "openai" or "api.openai.com" in provider.base_url

    def get(self, provider_model_name: str) -> ModelMetadata | None:
        return _OPENAI_MODELS.get(provider_model_name)


class ModelMetadataRegistry:
    def __init__(self, adapters: list[ProviderModelMetadataAdapter]) -> None:
        self._adapters = adapters

    def get(self, *, provider: Provider, provider_model_name: str) -> ModelMetadata | None:
        for adapter in self._adapters:
            if adapter.supports(provider):
                metadata = adapter.get(provider_model_name)
                if metadata is not None:
                    return metadata
        return None


def _frontier_model(
    provider_model_name: str,
    *,
    context_window: int,
    reasoning: bool = True,
) -> ModelMetadata:
    return ModelMetadata(
        provider_model_name=provider_model_name,
        input_modalities=["text", "vision"],
        output_modalities=["text"],
        context_window=context_window,
        capabilities={
            "chat": True,
            "embeddings": False,
            "vision": True,
            "tools": True,
            "json_mode": True,
            "streaming": True,
            "reasoning": reasoning,
        },
    )


_OPENAI_MODELS = {
    "gpt-5.4": _frontier_model("gpt-5.4", context_window=1_000_000),
    "gpt-5.4-mini": _frontier_model("gpt-5.4-mini", context_window=400_000),
    "gpt-5.4-nano": _frontier_model("gpt-5.4-nano", context_window=400_000),
    "gpt-5": _frontier_model("gpt-5", context_window=400_000),
    "gpt-5-mini": _frontier_model("gpt-5-mini", context_window=400_000),
    "gpt-5-nano": _frontier_model("gpt-5-nano", context_window=400_000),
    "gpt-4o-mini": _frontier_model(
        "gpt-4o-mini",
        context_window=128_000,
        reasoning=False,
    ),
    "o4-mini": _frontier_model("o4-mini", context_window=200_000),
}


default_model_metadata_registry = ModelMetadataRegistry([OpenAIModelMetadataAdapter()])
