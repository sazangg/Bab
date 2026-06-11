import { expect, test } from "@playwright/test";

import { loginAs } from "../helpers/auth";
import { createProviderRouteFixture, uniqueName } from "../helpers/data";

test("access policy creation accepts two UI routes before submit", async ({ page, request }) => {
  const firstRoute = await createProviderRouteFixture(request);
  const secondRoute = await createProviderRouteFixture(request);
  const policyName = uniqueName("E2E multi-route policy");

  await loginAs(page, "owner@example.com", "correct-password", "/policies");
  await page.getByRole("button", { name: "New access policy" }).click();

  await page.getByRole("textbox").first().fill(policyName);
  await page.getByRole("combobox").nth(1).click();
  await page.getByRole("option", { name: firstRoute.provider.name }).click();
  await expect(page.getByText(`${firstRoute.model.provider_model_name}`)).toBeVisible();
  await page.getByRole("button", { name: "Add route" }).click();

  await page.getByRole("combobox").nth(1).click();
  await page.getByRole("option", { name: secondRoute.provider.name }).click();
  await expect(page.getByText(`${secondRoute.model.provider_model_name}`)).toBeVisible();
  await page.getByRole("button", { name: "Add route" }).click();

  await expect(page.getByText("1 model")).toHaveCount(2);
  await page.getByRole("button", { name: "Create policy" }).click();
  await expect(page.getByText(policyName)).toBeVisible();
});
