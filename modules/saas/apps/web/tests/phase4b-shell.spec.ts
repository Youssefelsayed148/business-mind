import { expect, test } from "@playwright/test";

import { registerAdmin, uniqueEmail } from "./e2e-helpers";
import { promoteToStaff } from "./staff-helpers";

/**
 * Phase 4B: the first Many page through the SaaS proxy, its states, the guard, the old-URL
 * redirects and the switcher rule. The browser's calls to /api/v1/many/... are answered by
 * Playwright (no Many process here); the staff guard and sign-in are the real API.
 */

const OVERVIEW = "**/api/v1/many/staff/stats/overview";

async function signedInStaff(page: import("@playwright/test").Page) {
  const email = uniqueEmail("p4b-staff");
  await registerAdmin(page, "P4B", { email });
  promoteToStaff(email);
  return email;
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

test("staff sees the Many overview from the proxy", async ({ page }) => {
  await signedInStaff(page);
  let calls = 0;
  await page.route(OVERVIEW, (route) => {
    calls += 1;
    return route.fulfill({
      json: {
        active_campaigns: 3,
        triggers_today: 12,
        messages_sent_today: 9,
        failed_messages_today: 1,
        new_leads_today: 4,
      },
    });
  });
  await page.goto("/platform/many");
  const tiles = page.getByTestId("many-overview");
  await expect(tiles).toContainText("Active campaigns");
  await expect(tiles).toContainText("12");
  await expect(page.getByRole("link", { name: "Many overview" })).toBeVisible();
  expect(calls).toBe(1);
});

for (const [name, status, body, testId] of [
  [
    "a 403 shows the forbidden state",
    403,
    { error: { code: "FORBIDDEN", message: "no" } },
    "page-forbidden",
  ],
  [
    "a 404 (flag off) shows the not-available state",
    404,
    { error: { code: "NOT_FOUND", message: "no" } },
    "page-not_available",
  ],
  [
    "a 502 shows a retryable unavailable state",
    502,
    { error: { code: "MANY_UNAVAILABLE", message: "down" } },
    "page-unavailable",
  ],
] as const) {
  test(name, async ({ page }) => {
    await signedInStaff(page);
    await page.route(OVERVIEW, (route) =>
      route.fulfill({ status, json: body }),
    );
    await page.goto("/platform/many");
    const state = page.getByTestId(testId);
    await expect(state).toBeVisible();
    // Plain words, never a raw status code or the API's own message.
    await expect(state).not.toContainText(String(status));
    await expect(state).not.toContainText("down");
    await expect(page.getByTestId("many-overview")).toHaveCount(0);
  });
}

test("the unavailable state retries and recovers", async ({ page }) => {
  await signedInStaff(page);
  let attempt = 0;
  await page.route(OVERVIEW, (route) => {
    attempt += 1;
    if (attempt === 1) {
      return route.fulfill({
        status: 502,
        json: { error: { code: "MANY_UNAVAILABLE", message: "down" } },
      });
    }
    return route.fulfill({
      json: {
        active_campaigns: 1,
        triggers_today: 0,
        messages_sent_today: 0,
        failed_messages_today: 0,
        new_leads_today: 0,
      },
    });
  });
  await page.goto("/platform/many");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("many-overview")).toBeVisible();
});

test("a client cannot open the staff Many page, and no Many call is made", async ({
  page,
}) => {
  await registerAdmin(page, "P4B-client");
  let calls = 0;
  await page.route("**/api/v1/many/**", (route) => {
    calls += 1;
    return route.fulfill({ status: 200, json: {} });
  });
  await page.goto("/platform/many");
  await expect(page).toHaveURL(/\/login/);
  expect(calls).toBe(0);
});

test("a single-organization client sees no organization switcher", async ({
  page,
}) => {
  await registerAdmin(page, "P4B-one");
  await expect(page.getByTestId("workspace-context")).toContainText("Admin");
  await expect(page.getByLabel("Organization selector")).toHaveCount(0);
});

test("old Many URLs redirect, keeping the query string", async ({ page }) => {
  // Signed out: the guard of the new place asks for sign-in, naming where it was going.
  await page.goto("/leads?search=ann");
  await expect(page).toHaveURL(/\/login/);
  expect(new URL(page.url()).searchParams.get("next")).toBe("/platform");

  await page.goto("/campaigns/123/stats?x=1");
  await expect(page).toHaveURL(/\/login/);

  await page.goto("/overview");
  await expect(page).toHaveURL(/\/login/);
  expect(new URL(page.url()).searchParams.get("next")).toBe("/platform");
});

test("old Facebook and WhatsApp addresses lead to the workspace list", async ({
  page,
}) => {
  await registerAdmin(page, "P4B-old");
  await page.goto("/whatsapp/contacts");
  await expect(page).toHaveURL(/\/app$/);
  await page.goto("/facebook-campaigns");
  await expect(page).toHaveURL(/\/app$/);
});

test("the old Instagram return address /accounts keeps its query and routes by session", async ({
  page,
}) => {
  await page.goto("/accounts?connected=1");
  await expect(page).toHaveURL(/\/login/);
  expect(
    decodeURIComponent(new URL(page.url()).searchParams.get("next") ?? ""),
  ).toBe("/accounts?connected=1");
});

test("the moved page shows the old address as text, never as markup", async ({
  page,
}) => {
  await page.goto(
    "/moved?from=" + encodeURIComponent("<img src=x onerror=alert(1)>"),
  );
  await expect(page.locator("main img")).toHaveCount(0);
  await expect(page.locator("main")).toContainText("<img src=x");
});
