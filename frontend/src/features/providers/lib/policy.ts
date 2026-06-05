import {
  defaultCircuitBreakerPolicy,
  defaultRetryPolicy,
  STATUS_CODE_MAX,
  STATUS_CODE_MIN,
  type CircuitBreakerPolicyValues,
  type EditProviderValues,
  type RetryPolicyValues,
} from "./schemas";

function numberOrFallback(value: unknown, fallback: number) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
}

function coerceStatusCodes(value: unknown, fallback: readonly number[]) {
  if (!Array.isArray(value)) return [...fallback];
  const codes = value
    .map((item) => numberOrFallback(item, NaN))
    .filter((n) => Number.isFinite(n) && n >= STATUS_CODE_MIN && n <= STATUS_CODE_MAX);
  return Array.from(new Set(codes)).sort((a, b) => a - b);
}

export function mergeRetryPolicy(stored: unknown): RetryPolicyValues {
  const s = (stored && typeof stored === "object" ? stored : {}) as Record<string, unknown>;
  return {
    enabled: typeof s.enabled === "boolean" ? s.enabled : defaultRetryPolicy.enabled,
    max_attempts: numberOrFallback(s.max_attempts, defaultRetryPolicy.max_attempts),
    backoff:
      s.backoff === "constant" || s.backoff === "linear" || s.backoff === "exponential"
        ? s.backoff
        : defaultRetryPolicy.backoff,
    initial_delay_ms: numberOrFallback(s.initial_delay_ms, defaultRetryPolicy.initial_delay_ms),
    max_delay_ms: numberOrFallback(s.max_delay_ms, defaultRetryPolicy.max_delay_ms),
    retry_on_status: coerceStatusCodes(s.retry_on_status, defaultRetryPolicy.retry_on_status),
  };
}

export function mergeCircuitBreakerPolicy(stored: unknown): CircuitBreakerPolicyValues {
  const s = (stored && typeof stored === "object" ? stored : {}) as Record<string, unknown>;
  return {
    enabled: typeof s.enabled === "boolean" ? s.enabled : defaultCircuitBreakerPolicy.enabled,
    failure_threshold_pct: numberOrFallback(
      s.failure_threshold_pct,
      defaultCircuitBreakerPolicy.failure_threshold_pct,
    ),
    min_request_count: numberOrFallback(
      s.min_request_count,
      defaultCircuitBreakerPolicy.min_request_count,
    ),
    window_seconds: numberOrFallback(s.window_seconds, defaultCircuitBreakerPolicy.window_seconds),
    cooldown_seconds: numberOrFallback(
      s.cooldown_seconds,
      defaultCircuitBreakerPolicy.cooldown_seconds,
    ),
  };
}

export function buildProviderUpdatePayload(values: EditProviderValues) {
  return {
    name: values.name,
    ...(values.slug ? { slug: values.slug } : {}),
    base_url: values.base_url,
    description: values.description ? values.description : null,
    request_timeout_seconds:
      values.request_timeout_mode === "override" ? values.request_timeout_seconds : null,
    max_body_bytes:
      values.max_body_mode === "override" && values.max_body_bytes_kb !== undefined
        ? values.max_body_bytes_kb * 1024
        : null,
    max_concurrent_requests:
      values.max_concurrent_requests !== undefined ? values.max_concurrent_requests : null,
    model_sync_mode: values.model_sync_mode === "inherit" ? null : values.model_sync_mode,
    retry_policy: values.retry_policy_mode === "override" ? values.retry_policy : null,
    circuit_breaker_policy: values.circuit_breaker_policy,
  };
}
