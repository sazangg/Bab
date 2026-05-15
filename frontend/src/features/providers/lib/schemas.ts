import { z } from "zod";

export const STATUS_CODE_MIN = 100;
export const STATUS_CODE_MAX = 599;

export const modelModalities = ["text", "vision", "embedding", "image", "audio"];
export const modelCapabilityOptions = ["chat", "embeddings", "tools", "json_mode", "streaming"];

export const routingPolicyOptions = [
  {
    value: "priority",
    label: "Priority",
    description: "Always use the active credential with the lowest priority number.",
  },
  {
    value: "round_robin",
    label: "Round robin",
    description: "Rotate through active credentials by choosing the one used least recently.",
  },
  {
    value: "least_recently_used",
    label: "Least recently used",
    description: "Prefer the active credential with the oldest last-used timestamp.",
  },
  {
    value: "health_based",
    label: "Health based",
    description: "Prefer valid credentials before unchecked, degraded, or invalid credentials.",
  },
  {
    value: "weighted",
    label: "Weighted",
    description: "Randomly select a credential, with lower priority numbers receiving more weight.",
  },
  {
    value: "fallback",
    label: "Fallback",
    description:
      "Try credentials by priority and move to the next one on retryable upstream errors.",
  },
] as const;

export const createProviderSchema = z.object({
  name: z.string().min(1).max(255),
  slug: z.string().optional(),
  base_url: z.url(),
  credential_routing_policy: z.enum([
    "priority",
    "round_robin",
    "least_recently_used",
    "health_based",
    "weighted",
    "fallback",
  ]),
});

export type CreateProviderValues = z.infer<typeof createProviderSchema>;

export const retryPolicySchema = z.object({
  enabled: z.boolean(),
  max_attempts: z.coerce.number().int().min(1).max(10),
  backoff: z.enum(["constant", "linear", "exponential"]),
  initial_delay_ms: z.coerce.number().int().min(0),
  max_delay_ms: z.coerce.number().int().min(0),
  retry_on_status: z.array(z.number().int().min(STATUS_CODE_MIN).max(STATUS_CODE_MAX)),
});

export const fallbackPolicySchema = z.object({
  enabled: z.boolean(),
  trigger_on_status: z.array(z.number().int().min(STATUS_CODE_MIN).max(STATUS_CODE_MAX)),
  fallback_provider_ids: z.array(z.string()),
});

export const circuitBreakerPolicySchema = z.object({
  enabled: z.boolean(),
  failure_threshold_pct: z.coerce.number().int().min(0).max(100),
  min_request_count: z.coerce.number().int().min(0),
  window_seconds: z.coerce.number().int().min(1),
  cooldown_seconds: z.coerce.number().int().min(1),
});

const optionalPositiveInt = z.preprocess(
  (value) => (value === "" || value === null || value === undefined ? undefined : Number(value)),
  z.number().int().min(1).optional(),
);

export const editProviderSchema = z.object({
  name: z.string().min(1).max(255),
  slug: z.string().optional(),
  base_url: z.url(),
  description: z.string().max(1000).optional(),
  credential_routing_policy: z.enum([
    "priority",
    "round_robin",
    "least_recently_used",
    "health_based",
    "weighted",
    "fallback",
  ]),
  request_timeout_seconds: z.coerce.number().int().min(1).max(300),
  max_body_bytes_kb: optionalPositiveInt,
  max_concurrent_requests: optionalPositiveInt,
  retry_policy: retryPolicySchema,
  fallback_policy: fallbackPolicySchema,
  circuit_breaker_policy: circuitBreakerPolicySchema,
});

export const providerCredentialSchema = z.object({
  name: z.string().min(1).max(255),
  api_key: z.string().min(1),
  priority: z.number().int().min(0),
});

export type EditProviderValues = z.infer<typeof editProviderSchema>;
export type EditProviderInput = z.input<typeof editProviderSchema>;
export type ProviderCredentialValues = z.infer<typeof providerCredentialSchema>;
export type RoutingPolicyValue = EditProviderValues["credential_routing_policy"];
export type RetryPolicyValues = z.infer<typeof retryPolicySchema>;
export type FallbackPolicyValues = z.infer<typeof fallbackPolicySchema>;
export type CircuitBreakerPolicyValues = z.infer<typeof circuitBreakerPolicySchema>;

export const defaultRetryPolicy: RetryPolicyValues = {
  enabled: true,
  max_attempts: 3,
  backoff: "exponential",
  initial_delay_ms: 500,
  max_delay_ms: 10000,
  retry_on_status: [408, 429, 500, 502, 503, 504],
};

export const defaultFallbackPolicy: FallbackPolicyValues = {
  enabled: false,
  trigger_on_status: [502, 503, 504],
  fallback_provider_ids: [],
};

export const defaultCircuitBreakerPolicy: CircuitBreakerPolicyValues = {
  enabled: false,
  failure_threshold_pct: 50,
  min_request_count: 20,
  window_seconds: 60,
  cooldown_seconds: 30,
};

export const modelOfferingSchema = z.object({
  provider_model_name: z.string().min(1).max(255),
  alias: z.string().optional(),
  version: z.string().optional(),
  input_modalities: z.array(z.string()).min(1),
  output_modalities: z.array(z.string()).min(1),
  context_window: z.preprocess(
    (value) => (value === "" || value === null || value === undefined ? undefined : Number(value)),
    z.number().int().min(1).optional(),
  ),
  input_price_per_million_tokens: z.preprocess(
    (value) => (value === "" || value === null || value === undefined ? undefined : Number(value)),
    z.number().int().min(0).optional(),
  ),
  output_price_per_million_tokens: z.preprocess(
    (value) => (value === "" || value === null || value === undefined ? undefined : Number(value)),
    z.number().int().min(0).optional(),
  ),
  cached_input_price_per_million_tokens: z.preprocess(
    (value) => (value === "" || value === null || value === undefined ? undefined : Number(value)),
    z.number().int().min(0).optional(),
  ),
  capabilities: z.array(z.string()).default([]),
});

export type ModelOfferingFormInput = z.input<typeof modelOfferingSchema>;
export type ModelOfferingValues = z.output<typeof modelOfferingSchema>;
