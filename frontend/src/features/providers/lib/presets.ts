import type { ProviderResponse } from "@/shared/api/generated/schemas";

export const providerPresets = [
  {
    id: "openai",
    name: "OpenAI",
    slug: "openai",
    baseUrl: "https://api.openai.com/v1",
    description: "Official OpenAI API for GPT models.",
    simpleIcon: undefined,
  },
  {
    id: "anthropic",
    name: "Anthropic",
    slug: "anthropic",
    baseUrl: "https://api.anthropic.com/v1",
    description: "Anthropic Claude models via the OpenAI-compatible endpoint.",
    simpleIcon: "anthropic",
  },
  {
    id: "google",
    name: "Google AI",
    slug: "google-ai",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    description: "Gemini models via Google AI Studio.",
    simpleIcon: "google",
  },
  {
    id: "mistral",
    name: "Mistral AI",
    slug: "mistral",
    baseUrl: "https://api.mistral.ai/v1",
    description: "Mistral hosted models through their v1 API.",
    simpleIcon: "mistralai",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    slug: "openrouter",
    baseUrl: "https://openrouter.ai/api/v1",
    description: "Multi-provider OpenAI-compatible model router.",
    simpleIcon: "openrouter",
  },
  {
    id: "groq",
    name: "Groq",
    slug: "groq",
    baseUrl: "https://api.groq.com/openai/v1",
    description: "Groq OpenAI-compatible inference endpoint.",
    simpleIcon: undefined,
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    slug: "deepseek",
    baseUrl: "https://api.deepseek.com/v1",
    description: "DeepSeek chat and reasoning models.",
    simpleIcon: "deepseek",
  },
  {
    id: "perplexity",
    name: "Perplexity",
    slug: "perplexity",
    baseUrl: "https://api.perplexity.ai",
    description: "Perplexity sonar models with built-in search.",
    simpleIcon: "perplexity",
  },
  {
    id: "together",
    name: "Together AI",
    slug: "together",
    baseUrl: "https://api.together.xyz/v1",
    description: "Open-source models hosted by Together.",
    simpleIcon: undefined,
  },
  {
    id: "fireworks",
    name: "Fireworks",
    slug: "fireworks",
    baseUrl: "https://api.fireworks.ai/inference/v1",
    description: "Fast open-source inference hosted by Fireworks.",
    simpleIcon: undefined,
  },
  {
    id: "cerebras",
    name: "Cerebras",
    slug: "cerebras",
    baseUrl: "https://api.cerebras.ai/v1",
    description: "Cerebras wafer-scale inference.",
    simpleIcon: undefined,
  },
  {
    id: "huggingface",
    name: "Hugging Face",
    slug: "huggingface",
    baseUrl: "https://api-inference.huggingface.co/v1",
    description: "Inference Endpoints on the Hugging Face Hub.",
    simpleIcon: "huggingface",
  },
  {
    id: "ollama",
    name: "Ollama",
    slug: "ollama",
    baseUrl: "http://localhost:11434/v1",
    description: "Local Ollama runtime exposed on this machine.",
    simpleIcon: "ollama",
  },
] as const;

export type ProviderPreset = (typeof providerPresets)[number];

export type ProviderCatalogEntry = {
  key: string;
  name: string;
  slug?: string;
  baseUrl: string;
  description: string;
  provider?: ProviderResponse;
  preset?: ProviderPreset;
  simpleIcon?: string;
  isCustom: boolean;
};
