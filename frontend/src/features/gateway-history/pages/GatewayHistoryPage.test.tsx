import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGatewayHistoryParams, GatewayHistoryPage } from "./GatewayHistoryPage";

const listRequests = vi.hoisted(() => vi.fn());

vi.mock("@/shared/api/generated/gateway-history/gateway-history", () => ({
  useListGatewayRequestsApiV1GatewayHistoryRequestsGet: listRequests,
}));

vi.mock("@/features/gateway-history/components/RequestTraceSheet", () => ({
  RequestTraceSheet: ({ gatewayRequestId }: { gatewayRequestId: string | null }) =>
    gatewayRequestId ? <div>Trace {gatewayRequestId}</div> : null,
}));

describe("GatewayHistoryPage", () => {
  beforeEach(() => {
    listRequests.mockImplementation((params) => ({
      data: {
        status: 200,
        data: {
          items: [gatewayRequest()],
          has_more: true,
          limit: 25,
          offset: params.offset,
        },
      },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    }));
  });

  it("resets pagination when search changes and sends current query parameters", async () => {
    const user = userEvent.setup();
    render(<GatewayHistoryPage />);

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(listRequests.mock.lastCall?.[0]).toMatchObject({ window: "24h", offset: 25 });

    await user.type(screen.getByRole("textbox", { name: "Search gateway requests" }), "model-a");
    await waitFor(() =>
      expect(listRequests.mock.lastCall?.[0]).toMatchObject({
        window: "24h",
        search: "model-a",
        offset: 0,
      }),
    );
  });

  it("builds status and fallback query parameters", () => {
    expect(
      buildGatewayHistoryParams({
        window: "7d",
        status: "failed",
        fallback: "attempted",
        search: "provider-a",
        page: 2,
      }),
    ).toEqual({
      window: "7d",
      status: "failed",
      fallback: "attempted",
      search: "provider-a",
      limit: 25,
      offset: 50,
    });
  });

  it("offers clear filters for a filtered empty result", async () => {
    listRequests.mockImplementation((params) => ({
      data: {
        status: 200,
        data: { items: [], has_more: false, limit: 25, offset: params.offset },
      },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    }));
    const user = userEvent.setup();
    render(<GatewayHistoryPage />);

    expect(screen.getByText("No gateway requests yet")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Search gateway requests" }), "missing");
    expect(screen.getByText("No gateway requests match")).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Clear filters" })[0]);
    expect(screen.getByRole("textbox", { name: "Search gateway requests" })).toHaveValue("");
  });

  it("opens a request trace from a keyboard-activated row", async () => {
    const user = userEvent.setup();
    render(<GatewayHistoryPage />);

    const row = screen.getByText("request-").closest("tr");
    expect(row).not.toBeNull();
    row?.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByText("Trace gateway-request-1")).toBeInTheDocument();
  });
});

function gatewayRequest() {
  return {
    id: "gateway-request-1",
    request_id: "request-123",
    gateway_endpoint: "/v1/chat/completions",
    requested_model: "model-a",
    public_model_name: "model-a",
    project_name: "Project",
    team_name: "Team",
    final_provider_name: "Provider",
    involved_provider_names: ["Provider"],
    final_http_status: 200,
    final_error_code: null,
    outcome: "succeeded",
    started_at: "2026-01-01T00:00:00Z",
    duration_ms: 12,
  };
}
