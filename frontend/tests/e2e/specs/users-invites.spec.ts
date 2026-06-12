import { expect, test } from "@playwright/test";

import { loginAs } from "../helpers/auth";
import { uniqueEmail } from "../helpers/data";

test("owner-created invite exposes visible URL and copy action", async ({ page }) => {
  await loginAs(page, "owner@example.com", "correct-password", "/users");

  await page.locator("#users-invite-email").fill(uniqueEmail("invite"));
  await page.getByRole("button", { name: "Invite user" }).click();

  await expect(page.getByText("Latest invite link")).toBeVisible();
  await expect(
    page.locator('input[value^="http://127.0.0.1:"][value*="/accept-invite?token="]'),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy" })).toBeVisible();
});
