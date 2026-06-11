import { expect, test } from "@playwright/test";

import { loginAs } from "../helpers/auth";
import { uniqueName } from "../helpers/data";

test("guardrail policy can be created and assigned in one UI flow", async ({ page }) => {
  const policyName = uniqueName("E2E guardrail");

  await loginAs(page, "owner@example.com", "correct-password", "/guardrails");
  await page.getByRole("button", { name: "New policy" }).first().click();

  const sheet = page.locator('[data-slot="sheet-content"]');
  await page.getByRole("textbox").first().fill(policyName);
  await sheet.getByRole("combobox").first().click();
  await page.getByRole("option", { name: "Organization" }).click();
  await page.getByPlaceholder("gpt-5-mini").fill("gpt-5-mini");
  await page.getByRole("button", { name: "Create policy" }).click();

  await expect(page.getByText(policyName).first()).toBeVisible();
  await expect(page.getByRole("main").getByText("Organization", { exact: true })).toBeVisible();
});
