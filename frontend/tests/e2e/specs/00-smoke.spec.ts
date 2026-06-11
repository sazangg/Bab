import { expect, test } from "@playwright/test";

import { apiGet, apiLogin } from "../helpers/api";
import { loginAs } from "../helpers/auth";

test("owner can load V1 shell and core route surfaces", async ({ page }) => {
  await loginAs(page);

  for (const route of [
    ["/", "Gateway home"],
    ["/teams", "Teams"],
    ["/projects", "Projects"],
    ["/users", "Users"],
    ["/settings", "Settings"],
  ] as const) {
    await loginAs(page, "owner@example.com", "correct-password", route[0]);
    await expect(page.getByRole("heading", { name: route[1] })).toBeVisible();
  }
});

test("fresh E2E bootstrap has no default teams", async ({ page, request }) => {
  const headers = await apiLogin(request);
  const teams = await apiGet<Array<{ name: string }>>(request, "/api/v1/teams", headers);
  expect(teams).toEqual([]);

  await loginAs(page, "owner@example.com", "correct-password", "/teams");
  await expect(page.getByText("No teams yet")).toBeVisible();
  await expect(page.getByText("Default Team")).toHaveCount(0);
});
