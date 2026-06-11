import { expect, type Page } from "@playwright/test";

export async function loginAs(
  page: Page,
  email = "owner@example.com",
  password = "correct-password",
  target = "/",
) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => url.pathname !== "/login");
  if (target !== "/") {
    await page.evaluate((nextPath) => {
      window.history.pushState(null, "", nextPath);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }, target);
    await expect(page).toHaveURL(new RegExp(`${target.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
  }
}
