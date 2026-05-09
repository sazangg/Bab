import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Outlet } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";

vi.mock("@/features/setup/components/SetupRedirect", () => ({
  SetupRedirect: () => <Outlet />,
}));

vi.mock("@/features/auth/components/AuthGate", () => ({
  AuthGate: () => <Outlet />,
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
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppRoutes", () => {
  it("renders the login route", () => {
    renderRoute("/login");

    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("renders the setup route", () => {
    renderRoute("/setup");

    expect(screen.getByRole("heading", { name: "Create admin" })).toBeInTheDocument();
  });

  it("redirects unknown routes to login", () => {
    renderRoute("/missing");

    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});
