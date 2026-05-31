from dataclasses import dataclass, field
from typing import Protocol

from app.modules.providers.internal.models import Provider


@dataclass(frozen=True)
class ModelPricingMetadata:
    input_price_per_million_tokens: int | None = None
    output_price_per_million_tokens: int | None = None
    cached_input_price_per_million_tokens: int | None = None
    catalog_version: str | None = None


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
    metadata_version: str | None = None


class ProviderModelMetadataAdapter(Protocol):
    def supports(self, provider: Provider) -> bool: ...

    def get(self, provider_model_name: str) -> ModelMetadata | None: ...


class OpenAIModelMetadataAdapter:
    def supports(self, provider: Provider) -> bool:
        slug = provider.slug or ""
        return slug == "openai" or "api.openai.com" in provider.base_url

    def get(self, provider_model_name: str) -> ModelMetadata | None:
        return _OPENAI_MODELS.get(provider_model_name)


class StaticProviderModelMetadataAdapter:
    def __init__(
        self,
        *,
        provider_slugs: set[str],
        base_url_markers: set[str],
        models: dict[str, ModelMetadata],
    ) -> None:
        self._provider_slugs = provider_slugs
        self._base_url_markers = base_url_markers
        self._models = models

    def supports(self, provider: Provider) -> bool:
        slug = provider.slug or ""
        base_url = provider.base_url or ""
        return slug in self._provider_slugs or any(
            marker in base_url for marker in self._base_url_markers
        )

    def get(self, provider_model_name: str) -> ModelMetadata | None:
        return self._models.get(provider_model_name)


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
        metadata_version="2026-05-31",
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


def _chat_model(
    provider_model_name: str,
    *,
    context_window: int,
    input_price_per_million_tokens: int | None = None,
    output_price_per_million_tokens: int | None = None,
    cached_input_price_per_million_tokens: int | None = None,
    vision: bool = False,
    tools: bool = True,
    json_mode: bool = True,
    reasoning: bool = False,
) -> ModelMetadata:
    return ModelMetadata(
        provider_model_name=provider_model_name,
        metadata_version="2026-05-31",
        input_modalities=["text", "vision"] if vision else ["text"],
        output_modalities=["text"],
        context_window=context_window,
        capabilities={
            "chat": True,
            "embeddings": False,
            "vision": vision,
            "tools": tools,
            "json_mode": json_mode,
            "streaming": True,
            "reasoning": reasoning,
        },
        pricing=ModelPricingMetadata(
            input_price_per_million_tokens=input_price_per_million_tokens,
            output_price_per_million_tokens=output_price_per_million_tokens,
            cached_input_price_per_million_tokens=cached_input_price_per_million_tokens,
            catalog_version="2026-05-31",
        ),
    )


_OPENAI_MODELS = {
    "gpt-5.4": _frontier_model("gpt-5.4", context_window=1_000_000),
    "gpt-5.4-mini": _frontier_model("gpt-5.4-mini", context_window=400_000),
    "gpt-5.4-nano": _frontier_model("gpt-5.4-nano", context_window=400_000),
    "gpt-5": _frontier_model("gpt-5", context_window=400_000),
    "gpt-5-mini": _frontier_model("gpt-5-mini", context_window=400_000),
    "gpt-5-nano": _frontier_model("gpt-5-nano", context_window=400_000),
    "gpt-4o-mini": _chat_model(
        "gpt-4o-mini",
        context_window=128_000,
        input_price_per_million_tokens=15,
        output_price_per_million_tokens=60,
        cached_input_price_per_million_tokens=8,
        vision=True,
        reasoning=False,
    ),
    "o4-mini": _frontier_model("o4-mini", context_window=200_000),
}

_MISTRAL_MODELS = {
    "mistral-large-latest": _chat_model(
        "mistral-large-latest",
        context_window=128_000,
        input_price_per_million_tokens=200,
        output_price_per_million_tokens=600,
    ),
    "mistral-small-latest": _chat_model(
        "mistral-small-latest",
        context_window=128_000,
        input_price_per_million_tokens=10,
        output_price_per_million_tokens=30,
    ),
}

_GOOGLE_AI_MODELS = {
    "gemini-2.5-pro": _chat_model(
        "gemini-2.5-pro",
        context_window=1_000_000,
        input_price_per_million_tokens=125,
        output_price_per_million_tokens=1000,
        vision=True,
        reasoning=True,
    ),
    "gemini-2.5-flash": _chat_model(
        "gemini-2.5-flash",
        context_window=1_000_000,
        input_price_per_million_tokens=30,
        output_price_per_million_tokens=250,
        vision=True,
        reasoning=True,
    ),
}

_GROQ_MODELS = {
    "llama-3.3-70b-versatile": _chat_model(
        "llama-3.3-70b-versatile",
        context_window=128_000,
        input_price_per_million_tokens=59,
        output_price_per_million_tokens=79,
    ),
    "openai/gpt-oss-120b": _chat_model(
        "openai/gpt-oss-120b",
        context_window=131_000,
        input_price_per_million_tokens=15,
        output_price_per_million_tokens=75,
        reasoning=True,
    ),
}

_DEEPSEEK_MODELS = {
    "deepseek-chat": _chat_model(
        "deepseek-chat",
        context_window=64_000,
        input_price_per_million_tokens=27,
        output_price_per_million_tokens=110,
    ),
    "deepseek-reasoner": _chat_model(
        "deepseek-reasoner",
        context_window=64_000,
        input_price_per_million_tokens=55,
        output_price_per_million_tokens=219,
        reasoning=True,
    ),
}

_OPENROUTER_MODELS = {
    "openai/gpt-4o-mini": _chat_model(
        "openai/gpt-4o-mini",
        context_window=128_000,
        input_price_per_million_tokens=15,
        output_price_per_million_tokens=60,
        vision=True,
    ),
    "anthropic/claude-3.5-sonnet": _chat_model(
        "anthropic/claude-3.5-sonnet",
        context_window=200_000,
        input_price_per_million_tokens=300,
        output_price_per_million_tokens=1500,
        vision=True,
    ),
}

default_model_metadata_registry = ModelMetadataRegistry(
    [
        OpenAIModelMetadataAdapter(),
        StaticProviderModelMetadataAdapter(
            provider_slugs={"mistral"},
            base_url_markers={"api.mistral.ai"},
            models=_MISTRAL_MODELS,
        ),
        StaticProviderModelMetadataAdapter(
            provider_slugs={"google-ai"},
            base_url_markers={"generativelanguage.googleapis.com"},
            models=_GOOGLE_AI_MODELS,
        ),
        StaticProviderModelMetadataAdapter(
            provider_slugs={"groq"},
            base_url_markers={"api.groq.com"},
            models=_GROQ_MODELS,
        ),
        StaticProviderModelMetadataAdapter(
            provider_slugs={"deepseek"},
            base_url_markers={"api.deepseek.com"},
            models=_DEEPSEEK_MODELS,
        ),
        StaticProviderModelMetadataAdapter(
            provider_slugs={"openrouter"},
            base_url_markers={"openrouter.ai"},
            models=_OPENROUTER_MODELS,
        ),
    ]
)
