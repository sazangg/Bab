import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppRoutes } from "@/app/router";

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
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
