import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RequestTraceSheet } from "./RequestTraceSheet";

const traceHook = vi.hoisted(() => vi.fn());

vi.mock("@/shared/api/generated/gateway-history/gateway-history", () => ({
  useGetGatewayRequestTraceApiV1GatewayHistoryRequestsGatewayRequestIdGet: traceHook,
}));

const trace = {
  request: {
    id: "gateway-request-1",
    request_id: "external-request-1",
    gateway_endpoint: "/v1/chat/completions",
    requested_model: "gpt-public",
    public_model_name: "GPT Public",
    final_http_status: 200,
    attempt_count: 2,
    fallback_attempted: true,
    started_at: "2026-06-19T10:00:00Z",
    completed_at: "2026-06-19T10:00:02Z",
    trace_expires_at: "2026-06-26T10:00:00Z",
  },
  timeline: [
    {
      timestamp: "2026-06-19T10:00:00Z",
      kind: "request",
      title: "Request started",
      status: "started",
      severity: "info",
    },
    {
      timestamp: "2026-06-19T10:00:01Z",
      kind: "usage_record",
      title: "Usage recorded",
      status: "reserved",
      severity: "info",
      summary: "Limit reservation recorded.",
    },
  ],
  route_attempts: [
    {
      id: "attempt-1",
      org_id: "org-1",
      gateway_request_id: "gateway-request-1",
      attempt_index: 0,
      provider_name: "Primary AI",
      provider_model: "primary-model",
      status: "failed",
      http_status: 502,
      error_code: "provider_error",
      failure_reason: null,
      latency_ms: 1200,
      cost_cents: 0,
      usage_source: "estimated",
      pricing_snapshot: {},
      capability_snapshot: {},
      route_snapshot: {},
      started_at: "2026-06-19T10:00:00Z",
      completed_at: "2026-06-19T10:00:01Z",
    },
    {
      id: "attempt-2",
      org_id: "org-1",
      gateway_request_id: "gateway-request-1",
      attempt_index: 1,
      provider_name: "Fallback AI",
      provider_model: "fallback-model",
      fallback_from_attempt_id: "attempt-1",
      status: "succeeded",
      http_status: 200,
      error_code: null,
      failure_reason: null,
      latency_ms: 800,
      cost_cents: 3,
      usage_source: "reported",
      pricing_snapshot: {},
      capability_snapshot: {},
      route_snapshot: {},
      started_at: "2026-06-19T10:00:01Z",
      completed_at: "2026-06-19T10:00:02Z",
    },
  ],
  policy_decisions: [
    {
      id: "decision-0",
      gateway_request_id: "gateway-request-1",
      decision_type: "access",
      stage: "request",
      outcome: "allowed",
      effective_action: "allow",
      enforced: true,
      reason_code: null,
      message: null,
      dimension_snapshot: { prompt_tokens: 10, matched_values: "[redacted]" },
      metadata: { prompt: "[redacted]", response_text: "[redacted]" },
      created_at: "2026-06-19T10:00:00Z",
    },
    {
      id: "decision-1",
      gateway_request_id: "gateway-request-1",
      decision_type: "limit",
      stage: "request",
      outcome: "would_deny",
      effective_action: "monitor",
      enforced: false,
      reason_code: "budget_exceeded",
      message: null,
      dimension_snapshot: {},
      metadata: {},
      created_at: "2026-06-19T10:00:00Z",
    },
  ],
  guardrail_events: [
    {
      id: "guardrail-1",
      org_id: "org-1",
      policy_id: "policy-1",
      policy_revision_id: "revision-1",
      rule_id: "rule-1",
      decision: "blocked",
      phase: "request",
      reason: "Sensitive content",
      team_id: null,
      project_id: null,
      virtual_key_id: null,
      provider_id: null,
      pool_id: null,
      request_id: "external-request-1",
      gateway_request_id: "gateway-request-1",
      route_attempt_id: null,
      requested_model: "gpt-public",
      provider_model: null,
      metadata: { matched_values: "[redacted]", matched_text: "[redacted]" },
      created_at: "2026-06-19T10:00:00Z",
    },
  ],
  usage_records: [
    {
      id: "usage-1",
      request_id: "external-request-1",
      gateway_request_id: "gateway-request-1",
      route_attempt_id: "attempt-2",
      requested_model: "gpt-public",
      provider_model: "fallback-model",
      provider_credential_id: "credential-1",
      provider_credential_name: "Fallback credential",
      provider_credential_prefix: "cred",
      http_status: 200,
      error_code: null,
      prompt_tokens: 10,
      completion_tokens: 20,
      total_tokens: 30,
      confirmed_spend_cents: 3,
      estimated_spend_cents: 0,
      spend_type: "confirmed",
      latency_ms: 800,
      created_at: "2026-06-19T10:00:02Z",
      dimension_snapshot: {},
    },
  ],
};

describe("RequestTraceSheet", () => {
  beforeEach(() => {
    traceHook.mockReturnValue({
      data: { status: 200, data: trace },
      isPending: false,
      error: null,
      refetch: vi.fn(),
    });
  });

  it("renders the timeline before trace detail sections", () => {
    render(<RequestTraceSheet gatewayRequestId="gateway-request-1" open onOpenChange={vi.fn()} />);

    const timeline = screen.getByText("Timeline");
    const routeAttempts = screen.getByText("Route attempts");

    expect(timeline.compareDocumentPosition(routeAttempts)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.getByText("Request started")).toBeInTheDocument();
    expect(screen.getByText("Limit reserved")).toBeInTheDocument();
  });

  it("uses compact operational labels for trace outcomes", () => {
    render(<RequestTraceSheet gatewayRequestId="gateway-request-1" open onOpenChange={vi.fn()} />);

    expect(screen.getAllByText("Fallback attempted").length).toBeGreaterThan(0);
    expect(screen.getByText("Provider failed")).toBeInTheDocument();
    expect(screen.getByText("Would deny")).toBeInTheDocument();
    expect(screen.getByText("Denied")).toBeInTheDocument();
    expect(screen.getByText("Allowed")).toBeInTheDocument();
  });

  it("does not render redacted raw prompt, response, or matched content", () => {
    render(<RequestTraceSheet gatewayRequestId="gateway-request-1" open onOpenChange={vi.fn()} />);

    expect(screen.queryByText("[redacted]")).not.toBeInTheDocument();
    expect(screen.queryByText("raw prompt")).not.toBeInTheDocument();
    expect(screen.queryByText("raw response")).not.toBeInTheDocument();
    expect(screen.queryByText("raw match")).not.toBeInTheDocument();
  });
});
