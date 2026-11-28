import { expect, test, type Page } from "@playwright/test";

import { registerAdmin } from "./e2e-helpers";

/**
 * Phase 5B: the people-across-channels view. Sign-in and the organization are real; the
 * customer-links answers are faked in the browser (the real routes answer 404 while the
 * data-unification flag is off, and the API behaviour is covered by the API tests).
 */

type Item = {
  id: string;
  platform: string;
  state: string;
  display_name: string | null;
  contact_id: string | null;
  contact_name: string | null;
  seen_at: string | null;
};

const ITEMS: Item[] = [
  {
    id: "l1",
    platform: "whatsapp",
    state: "linked",
    display_name: "dana_wa",
    contact_id: "c-1",
    contact_name: "Dana Cohen",
    seen_at: "2026-05-01T10:00:00Z",
  },
  {
    id: "l2",
    platform: "whatsapp",
    state: "many_only",
    display_name: "عميل جديد",
    contact_id: null,
    contact_name: null,
    seen_at: "2026-05-02T10:00:00Z",
  },
  {
    id: "l3",
    platform: "facebook",
    state: "many_only",
    display_name: "omar.fb",
    contact_id: null,
    contact_name: null,
    seen_at: null,
  },
];

async function csrf(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name === "chatbot_csrf")?.value ?? "";
}

async function fakeLinks(page: Page, status = 200) {
  const queries: string[] = [];
  await page.route("**/api/v1/tenants/*/customer-links**", async (route) => {
    const url = new URL(route.request().url());
    queries.push(url.search);
    if (status !== 200)
      return route.fulfill({
        status,
        json: { error: { code: "X", message: "no" } },
      });
    const platform = url.searchParams.get("platform");
    const items = platform
      ? ITEMS.filter((i) => i.platform === platform)
      : ITEMS;
    return route.fulfill({ json: { total: items.length, items } });
  });
  return queries;
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

test("the contacts page offers the view only when it answers, and the list shows everyone", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P5B");
  const queries = await fakeLinks(page);
  await page.goto(`/app/${tenantId}/contacts`);
  await page.getByRole("link", { name: "People across channels" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/${tenantId}/contacts/links$`));
  const table = page.getByTestId("people-across-channels");
  await expect(table).toContainText("Dana Cohen");
  await expect(table).toContainText("عميل جديد");
  await expect(table).toContainText("omar.fb");
  await expect(table).toContainText("Linked");
  await expect(table).toContainText("Outreach only");
  await expect(page.getByText("3 people")).toBeVisible();
  // Only the linked person has a chat contact to open.
  await expect(table.getByRole("link", { name: "Open contact" })).toHaveCount(
    1,
  );
  // A name written in Arabic decides its own direction.
  await expect(
    table.locator('strong[dir="auto"]', { hasText: "عميل" }),
  ).toHaveCount(1);
  // Filtering sends the choice to the API.
  await page.getByLabel("Channel", { exact: true }).selectOption("facebook");
  await expect(page.getByText("1 person")).toBeVisible();
  await expect
    .poll(() => queries.some((q) => q.includes("platform=facebook")))
    .toBe(true);
});

test("without the view (flag off) there is no button, and a direct visit says so", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P5B-off");
  await fakeLinks(page, 404);
  await page.goto(`/app/${tenantId}/contacts`);
  await expect(page.getByRole("heading", { name: "Contacts" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "People across channels" }),
  ).toHaveCount(0);
  await page.goto(`/app/${tenantId}/contacts/links`);
  await expect(page.getByText(/not turned on/i)).toBeVisible();
});

test("a failure is told plainly, not as an empty list", async ({ page }) => {
  const { tenantId } = await registerAdmin(page, "P5B-fail");
  await fakeLinks(page, 500);
  await page.goto(`/app/${tenantId}/contacts/links`);
  await expect(page.getByText(/could not load people/i)).toBeVisible();
});

test("the contact page lists the contact's channels when the view answers", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P5B-contact");
  const created = await page.request.post(
    `/api/v1/tenants/${tenantId}/contacts`,
    {
      headers: { "X-CSRF-Token": await csrf(page) },
      data: {
        display_name: "Dana Cohen",
        email: `dana.${Date.now()}@example.com`,
      },
    },
  );
  expect(created.status()).toBe(201);
  const contactId = ((await created.json()) as { id: string }).id;
  await page.route(
    `**/api/v1/tenants/${tenantId}/contacts/${contactId}/customer-links`,
    (route) => route.fulfill({ json: { items: [ITEMS[0]] } }),
  );
  await page.goto(`/app/${tenantId}/contacts/${contactId}`);
  const card = page.getByTestId("contact-channel-links");
  await expect(card).toContainText("WhatsApp");
  await expect(card).toContainText("Linked");
});

test("the contact page shows nothing extra when the view is off", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P5B-contact-off");
  const created = await page.request.post(
    `/api/v1/tenants/${tenantId}/contacts`,
    {
      headers: { "X-CSRF-Token": await csrf(page) },
      data: { display_name: "Omar", email: `omar.${Date.now()}@example.com` },
    },
  );
  const contactId = ((await created.json()) as { id: string }).id;
  await page.goto(`/app/${tenantId}/contacts/${contactId}`);
  await expect(
    page.getByRole("heading", { name: "Channel identities" }),
  ).toBeVisible();
  await expect(page.getByTestId("contact-channel-links")).toHaveCount(0);
});
