import { expect, test } from "@playwright/test";

import { loginAs } from "../helpers/auth";
import { createPermissionFixture } from "../helpers/data";

test("team and project admins only see their scoped teams and projects", async ({
  page,
  request,
}) => {
  const fixture = await createPermissionFixture(request);

  await loginAs(page, fixture.teamAdminEmail, "team-admin-password", "/teams");
  await expect(page.getByText(fixture.teamA.name)).toBeVisible();
  await expect(page.getByText(fixture.teamB.name)).toHaveCount(0);
  await loginAs(page, fixture.teamAdminEmail, "team-admin-password", "/projects");
  await expect(page.getByText(fixture.projectA.name)).toBeVisible();
  await expect(page.getByText(fixture.projectB.name)).toHaveCount(0);

  await page.context().clearCookies();
  await loginAs(page, fixture.projectAdminEmail, "project-admin-password", "/projects");
  await expect(page.getByText(fixture.projectA.name)).toBeVisible();
  await expect(page.getByText(fixture.projectB.name)).toHaveCount(0);
});
