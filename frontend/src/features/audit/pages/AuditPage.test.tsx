import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuditPage } from "./AuditPage";

const infiniteQuery = vi.hoisted(() => vi.fn());
const httpGet = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@tanstack/react-query", () => ({
  useInfiniteQuery: infiniteQuery,
}));

vi.mock("@/shared/api/http-client", () => ({
  httpClient: { get: httpGet },
}));

vi.mock("@/shared/lib/use-debounced-value", () => ({
  useDebouncedValue: (value: string) => value,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

describe("AuditPage", () => {
  beforeEach(() => {
    httpGet.mockReset();
    httpGet.mockResolvedValue({ data: { items: [], has_more: false } });
    toastSuccess.mockReset();
    toastError.mockReset();
    infiniteQuery.mockReturnValue({
      data: { pages: [{ items: [auditEvent()], has_more: false }] },
      isPending: false,
      isError: false,
      hasNextPage: false,
      isFetchingNextPage: false,
      refetch: vi.fn(),
      fetchNextPage: vi.fn(),
    });
  });

  it("passes search and entity filters to the cursor query", async () => {
    const user = userEvent.setup();
    render(<AuditPage />);

    await user.type(screen.getByRole("textbox", { name: "Search audit events" }), "member");
    await user.type(screen.getByRole("textbox", { name: "Filter by exact action" }), "user.update");

    const options = infiniteQuery.mock.lastCall?.[0];
    await options.queryFn({ pageParam: undefined });
    expect(httpGet).toHaveBeenCalledWith(
      "/api/v1/audit",
      expect.objectContaining({
        params: expect.objectContaining({ q: "member", action: "user.update", limit: 50 }),
      }),
    );
  });

  it("disables loading and shows an invalid date range", async () => {
    const user = userEvent.setup();
    render(<AuditPage />);

    await user.type(screen.getByLabelText("Audit start date"), "2026-06-30");
    await user.type(screen.getByLabelText("Audit end date"), "2026-06-01");

    expect(screen.getByText("Invalid date range")).toBeInTheDocument();
    expect(infiniteQuery.mock.lastCall?.[0].enabled).toBe(false);
  });

  it("shows chain verification results and export failures", async () => {
    httpGet.mockImplementation((url: string) => {
      if (url === "/api/v1/audit/verify") {
        return Promise.resolve({ data: { valid: true, checked_events: 4 } });
      }
      if (url === "/api/v1/audit/export") return Promise.reject(new Error("failed"));
      return Promise.resolve({ data: {} });
    });
    const user = userEvent.setup();
    render(<AuditPage />);

    await user.click(screen.getByRole("button", { name: "Verify chain" }));
    expect(await screen.findByText("Audit chain verified")).toBeInTheDocument();
    expect(screen.getByText("4 events were verified.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(toastError).toHaveBeenCalledWith("Audit export could not be downloaded.");
  });

  it("opens event details from a keyboard-activated row", async () => {
    const user = userEvent.setup();
    render(<AuditPage />);

    const row = screen.getByText("user.update").closest("tr");
    row?.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByText("Audit event details")).toBeInTheDocument();
  });
});

function auditEvent() {
  return {
    id: "audit-1",
    created_at: "2026-06-01T00:00:00Z",
    actor_email: "admin@example.com",
    actor_user_id: "user-1",
    actor_role: "org_admin",
    action: "user.update",
    entity_type: "user",
    entity_id: "user-2",
    metadata: {},
    signature_algorithm: "hmac-sha256",
    previous_hash: null,
    event_hash: "hash",
  };
}
