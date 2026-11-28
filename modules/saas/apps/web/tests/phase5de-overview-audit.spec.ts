import { expect, test } from "@playwright/test";

import { registerAdmin, uniqueEmail } from "./e2e-helpers";
import { promoteToStaff } from "./staff-helpers";

/**
 * Phase 5D and 5E: the combined overview on the people page and the combined audit trail for
 * staff. Sign-in is real; the new routes are faked in the browser (they answer 404 while their
 * flag is off, and the API behaviour is covered by the API tests).
 */

const OVERVIEW = {
  range: { from: "2026-05-01T00:00:00Z", to: "2026-05-31T00:00:00Z", days: 30 },
  people: {
    source: "Customer link",
    by_platform: {
      whatsapp: {
        linked: 1,
        many_only: 2,
        saas_only: 0,
        conflict: 0,
        total: 3,
      },
      instagram: {
        linked: 0,
        many_only: 1,
        saas_only: 0,
        conflict: 0,
        total: 1,
      },
      facebook: {
        linked: 0,
        many_only: 0,
        saas_only: 1,
        conflict: 0,
        total: 1,
      },
    },
    known_to_outreach: 4,
    known_to_chat: 2,
  },
  chat: {
    source: "Chat inbox",
    contacts: 2,
    new_contacts: 2,
    conversations: 2,
    handoffs: 1,
    messages: { visitor: 3, ai: 1, agent: 1 },
  },
  ai: {
    source: "Chat inbox",
    calls: 2,
    tokens: 150,
    calls_with_cost: 1,
    cost_usd: 0.01,
  },
  not_available: ["Messages handled by the outreach service, per organization"],
};

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

test("the people page shows the combined overview and re-asks for another period", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P5D");
  const asked: string[] = [];
  await page.route("**/api/v1/tenants/*/customer-overview**", (route) => {
    asked.push(new URL(route.request().url()).search);
    return route.fulfill({ json: OVERVIEW });
  });
  await page.route("**/api/v1/tenants/*/customer-links**", (route) =>
    route.fulfill({ json: { total: 0, items: [] } }),
  );
  await page.route("**/api/v1/tenants/*/erasure-cases**", (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.goto(`/app/${tenantId}/contacts/links`);
  const people = page.getByTestId("overview-people");
  await expect(people).toContainText("WhatsApp");
  await expect(people).toContainText("Instagram");
  const numbers = page.getByTestId("overview-numbers");
  await expect(numbers).toContainText("2 conversations (1 handed to a person)");
  await expect(numbers).toContainText("3 visitor, 1 bot and 1 agent messages");
  await expect(numbers).toContainText("2 calls, 150 tokens");
  await expect(numbers).toContainText("0.010 USD (1 measured call)");
  await expect(numbers).toContainText("Not available here");
  await page.getByLabel("Period").selectOption("90");
  await expect.poll(() => asked.some((q) => q.includes("days=90"))).toBe(true);
});

test("staff see the combined audit trail with a source on every row", async ({
  page,
}) => {
  const email = uniqueEmail("p5e-staff");
  await registerAdmin(page, "P5E", { email });
  promoteToStaff(email);
  const asked: string[] = [];
  await page.route("**/api/v1/platform/audit**", (route) => {
    asked.push(new URL(route.request().url()).search);
    return route.fulfill({
      json: {
        items: [
          {
            source: "many",
            at: "2026-05-02T10:00:00Z",
            action: "send_failed",
            summary: "Message failed",
            level: "error",
            tenant_id: null,
          },
          {
            source: "saas",
            at: "2026-05-01T10:00:00Z",
            action: "customer_erasure.complete",
            summary: "customer erasure complete",
            level: "info",
            tenant_id: "t-1",
          },
        ],
        many_unavailable: false,
        notes: ["Outreach-service entries are not tied to one organization."],
      },
    });
  });
  await page.goto("/platform/audit");
  const table = page.getByTestId("combined-audit");
  await expect(table).toContainText("Outreach service");
  await expect(table).toContainText("Chat inbox");
  await expect(table).toContainText("send_failed");
  await expect(table).toContainText("customer_erasure.complete");
  await expect(page.getByText("not tied to one organization")).toBeVisible();
  await page.getByLabel("Source").selectOption("saas");
  await expect
    .poll(() => asked.some((q) => q.includes("source=saas")))
    .toBe(true);
});

test("the logs page links to the audit trail only when it answers", async ({
  page,
}) => {
  const email = uniqueEmail("p5e-logs");
  await registerAdmin(page, "P5E-logs", { email });
  promoteToStaff(email);
  await page.route("**/api/v1/many/staff/**", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/v1/platform/audit**", (route) =>
    route.fulfill({
      json: { items: [], many_unavailable: false, notes: [] },
    }),
  );
  await page.goto("/platform/logs");
  await expect(
    page.getByRole("link", { name: "Combined audit trail" }),
  ).toBeVisible();
  await page.unroute("**/api/v1/platform/audit**");
  await page.route("**/api/v1/platform/audit**", (route) =>
    route.fulfill({
      status: 404,
      json: { error: { code: "NOT_FOUND", message: "no" } },
    }),
  );
  await page.reload();
  await expect(page.getByRole("heading", { name: "Logs" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Combined audit trail" }),
  ).toHaveCount(0);
});

test("without the audit view a direct visit says so", async ({ page }) => {
  const email = uniqueEmail("p5e-off");
  await registerAdmin(page, "P5E-off", { email });
  promoteToStaff(email);
  await page.route("**/api/v1/platform/audit**", (route) =>
    route.fulfill({
      status: 404,
      json: { error: { code: "NOT_FOUND", message: "no" } },
    }),
  );
  await page.goto("/platform/audit");
  await expect(page.getByText(/not turned on/i)).toBeVisible();
});
