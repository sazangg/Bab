import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Outlet } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { TooltipProvider } from "@/components/ui/tooltip";

vi.mock("@/features/auth/components/AuthGate", () => ({
  AuthGate: () => <Outlet />,
}));

vi.mock("@/features/auth/components/ProtectedRoute", () => ({
  ProtectedRoute: () => <Outlet />,
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
  it("renders the login route", () => {
    renderRoute("/login");

    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("renders the dashboard home route", () => {
    renderRoute("/");

    expect(screen.getByRole("heading", { name: "Gateway home" })).toBeInTheDocument();
  });

  it("redirects unknown routes to login", () => {
    renderRoute("/missing");

    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });
});
