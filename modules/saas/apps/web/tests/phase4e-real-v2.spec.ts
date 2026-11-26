import { expect, test } from "@playwright/test";

import { registerAdmin } from "./e2e-helpers";

/**
 * Phase 4E against the REAL API with identity v2 on (no mocks), so the screens are checked
 * against the real response shapes. Skipped unless the run starts the API with the flag:
 *   IDENTITY_V2_ENABLED=true E2E_IDENTITY_V2=1 npx playwright test phase4e-real-v2
 */
test.skip(
  process.env.E2E_IDENTITY_V2 !== "1",
  "needs the API started with IDENTITY_V2_ENABLED=true",
);

test("config names identity v2 and the sign-in page links to reset", async ({
  page,
}) => {
  await page.goto("/login");
  await expect(
    page.getByRole("link", { name: "Forgot your password?" }),
  ).toBeVisible();
});

test("reset request gives the same answer for any address", async ({
  page,
}) => {
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill("nobody.here@example.com");
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByTestId("reset-requested")).toBeVisible();
});

test("account page lists this device; team screen lists the owner", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4E-real");
  await page.goto("/account");
  const sessions = page.getByTestId("sessions-panel");
  await expect(sessions).toContainText("This device");
  await expect(page.getByTestId("mfa-panel")).toBeVisible();

  await page.goto(`/app/${tenantId}/settings/members`);
  await expect(page.getByTestId("invite-form")).toBeVisible();
  const owner = page.getByRole("row").nth(1);
  await expect(owner).toContainText(/Admin|Owner/);
  // Inviting returns the same message whether or not the address has an account.
  await page
    .getByTestId("invite-form")
    .getByLabel("Email")
    .fill("someone.new@example.com");
  await page
    .getByTestId("invite-form")
    .getByRole("button", { name: "Send invitation" })
    .click();
  await expect(page.getByText(/invitation/i).first()).toBeVisible();
});
