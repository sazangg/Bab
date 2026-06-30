import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Outlet } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { TooltipProvider } from "@/components/ui/tooltip";

const protectedRouteMock = vi.hoisted(() => vi.fn(() => <Outlet />));

vi.mock("@/features/auth/components/AuthGate", () => ({
  AuthGate: () => <Outlet />,
}));

vi.mock("@/features/auth/components/ProtectedRoute", () => ({
  ProtectedRoute: protectedRouteMock,
}));

function renderRoute(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("AppRoutes", () => {
  beforeEach(() => {
    protectedRouteMock.mockClear();
  });

  it("renders the login route", async () => {
    renderRoute("/login");

    expect(await screen.findByLabelText("Email")).toBeInTheDocument();
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
  });

  it("renders the dashboard home route", async () => {
    renderRoute("/");

    expect(await screen.findByRole("heading", { name: "Home" })).toBeInTheDocument();
  });

  it("redirects unknown routes to login", async () => {
    renderRoute("/missing");

    expect(await screen.findByLabelText("Email")).toBeInTheDocument();
  });

  it("guards API Docs with key-manager access", () => {
    renderRoute("/api-docs");

    expect(protectedRouteMock).toHaveBeenCalledWith(
      expect.objectContaining({ requireKeyManager: true }),
      undefined,
    );
  });

  it("guards Playground with key-manager access", () => {
    renderRoute("/playground");

    expect(protectedRouteMock).toHaveBeenCalledWith(
      expect.objectContaining({ requireKeyManager: true }),
      undefined,
    );
  });

  it("guards Virtual keys with key-manager access", () => {
    renderRoute("/virtual-keys");

    expect(protectedRouteMock).toHaveBeenCalledWith(
      expect.objectContaining({ requireKeyManager: true }),
      undefined,
    );
  });

  it("guards Gateway history with gateway-history scope access", () => {
    renderRoute("/gateway-history");

    expect(protectedRouteMock).toHaveBeenCalledWith(
      expect.objectContaining({ allowGatewayHistoryScope: true }),
      undefined,
    );
  });

  it("guards Setup with organization-admin access", () => {
    renderRoute("/setup");

    expect(protectedRouteMock).toHaveBeenCalledWith(
      expect.objectContaining({ requireOrgAdminSurface: true }),
      undefined,
    );
  });
});
