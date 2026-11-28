import { expect, test, type Page } from "@playwright/test";

import { registerAdmin } from "./e2e-helpers";

/**
 * Phase 5C: erasing a person from the people-across-channels page. Sign-in is real; the
 * customer-links and erasure answers are faked in the browser (the API behaviour, including the
 * Many call, is covered by the API tests).
 */

const PERSON = {
  id: "l1",
  platform: "whatsapp",
  state: "many_only",
  display_name: "dana_wa",
  contact_id: null,
  contact_name: null,
  seen_at: null,
};

type Case = {
  id: string;
  platform: string;
  state: string;
  reason: string | null;
  message: string | null;
  created_at: string;
  completed_at: string | null;
};

const CASE = (state: string, message: string | null = null): Case => ({
  id: "case-1",
  platform: "whatsapp",
  state,
  reason: state === "needs_action" ? "many_unavailable" : null,
  message,
  created_at: "2026-05-01T10:00:00Z",
  completed_at: state === "complete" ? "2026-05-01T10:01:00Z" : null,
});

async function fake(page: Page, firstAnswer: Case, retryAnswer?: Case) {
  const calls: { path: string; body: unknown }[] = [];
  let cases: Case[] = [];
  await page.route("**/api/v1/tenants/*/customer-links**", (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === "POST") {
      calls.push({ path: url.pathname, body: route.request().postDataJSON() });
      cases = [firstAnswer];
      return route.fulfill({ status: 202, json: firstAnswer });
    }
    return route.fulfill({ json: { total: 1, items: [PERSON] } });
  });
  await page.route("**/api/v1/tenants/*/erasure-cases**", (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === "POST") {
      calls.push({ path: url.pathname, body: null });
      cases = [retryAnswer ?? firstAnswer];
      return route.fulfill({ status: 202, json: retryAnswer ?? firstAnswer });
    }
    return route.fulfill({ json: { items: cases } });
  });
  return calls;
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

test("erasing asks first, sends one request id, and shows the finished case", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P5C");
  const calls = await fake(page, CASE("complete"));
  await page.goto(`/app/${tenantId}/contacts/links`);
  await page.getByTestId("erase-l1").click();
  const dialog = page.getByRole("dialog", { name: /Erase dana_wa/ });
  await expect(dialog).toContainText("cannot be undone");
  await expect(dialog).toContainText("Their other channels stay");
  expect(calls).toEqual([]); // nothing is sent before the confirmation
  await dialog.getByRole("button", { name: "Erase this person" }).click();
  await expect(page.getByText("The person was erased.")).toBeVisible();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].path).toBe(
    `/api/v1/tenants/${tenantId}/customer-links/l1/erase`,
  );
  expect((calls[0].body as { request_id: string }).request_id).toMatch(
    /^[0-9a-f-]{36}$/,
  );
  const list = page.getByTestId("erasure-cases");
  await expect(list).toContainText("WhatsApp");
  await expect(list).toContainText("Complete");
  await expect(list.getByRole("button", { name: "Try again" })).toHaveCount(0);
});

test("a stopped case says why in plain words and can be tried again", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P5C-retry");
  const calls = await fake(
    page,
    CASE(
      "needs_action",
      "The outreach service did not answer. Try again in a moment.",
    ),
    CASE("complete"),
  );
  await page.goto(`/app/${tenantId}/contacts/links`);
  await page.getByTestId("erase-l1").click();
  await page
    .getByRole("dialog", { name: /Erase dana_wa/ })
    .getByRole("button", { name: "Erase this person" })
    .click();
  const list = page.getByTestId("erasure-cases");
  await expect(list).toContainText("Needs attention");
  await expect(list).toContainText("did not answer");
  await list.getByRole("button", { name: "Try again" }).click();
  await expect(list).toContainText("Complete");
  expect(calls.map((c) => c.path)).toEqual([
    `/api/v1/tenants/${tenantId}/customer-links/l1/erase`,
    `/api/v1/tenants/${tenantId}/erasure-cases/case-1/retry`,
  ]);
});
