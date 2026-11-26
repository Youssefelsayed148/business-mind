import { expect, test, type Page } from "@playwright/test";

import { registerAdmin } from "./e2e-helpers";

/**
 * Phase 4C: the WhatsApp outreach pages (contacts, templates, campaigns, health) in the
 * organization shell. Sign-in and the organization are real; the browser's calls to
 * /api/v1/many/orgs/{tenant}/whatsapp/... are answered by Playwright (no Many process).
 */

type Call = {
  method: string;
  path: string; // below /whatsapp/, without the query
  query: URLSearchParams;
  raw: string | null;
  json: unknown;
};
type Reply = { status?: number; json?: unknown };
type Handler = Reply | ((call: Call) => Reply);

const ACCOUNT = {
  id: "acc-1",
  phone_number_id: "111",
  display_phone_number: "+1 555 0100",
};
const ACCOUNT_2 = {
  id: "acc-2",
  phone_number_id: "222",
  display_phone_number: "+1 555 0200",
};
const HEALTH = {
  quality_rating: "GREEN",
  messaging_limit_tier: "TIER_1K",
  outreach_paused: false,
  outreach_paused_reason: null,
  health_checked_at: "2026-01-01T10:00:00Z",
  health_age_seconds: 60,
  sent_recipient_count_24h: 5,
  daily_cap: 250,
  outreach_enabled: true,
  ctwa_counts_as_consent: false,
  transactional_utility_attested: false,
  opt_in_keywords: ["START"],
  opt_out_keywords: ["STOP"],
  outreach_daily_cap: 250,
};
const CONTACT = {
  id: "c-1",
  whatsapp_account_id: "acc-1",
  wa_id: "15550001111",
  display_name: "Dana Cohen",
  marketing_consent: "unknown",
  consent_source: "inbound_message",
  consent_at: null,
  created_at: "2026-01-01T10:00:00Z",
};
const TEMPLATE = {
  id: "t-1",
  whatsapp_account_id: "acc-1",
  name: "seasonal_offer",
  language: "en_US",
  category: "marketing",
  status: "approved",
  components: [{ type: "BODY", text: "Hello {{1}}, your offer is ready." }],
  last_synced_at: null,
  created_at: "2026-01-01T10:00:00Z",
};
const DRAFT = {
  ...TEMPLATE,
  id: "t-2",
  name: "draft_one",
  status: "draft",
  components: [{ type: "BODY", text: "Hi there" }],
};
const CAMPAIGN = {
  id: "cp-1",
  whatsapp_account_id: "acc-1",
  template_id: "t-1",
  name: "Spring push",
  status: "running",
  throttle_per_minute: 30,
  variable_mapping: {},
  total_recipients: 10,
  sent_count: 4,
  delivered_count: 3,
  read_count: 2,
  failed_count: 1,
  skipped_count: 2,
  created_at: "2026-01-02T10:00:00Z",
};
const STATS = (campaign: Record<string, unknown> = CAMPAIGN) => ({
  campaign,
  recipient_statuses: { sent: 4, outcome_unknown: 1 },
  reasons: { no_marketing_consent: 2 },
  row_count: 10,
});

/** Answer every Many call; the default routes give a healthy account. */
async function fakeMany(
  page: Page,
  tenantId: string,
  routes: Record<string, Handler> = {},
) {
  const calls: Call[] = [];
  const table: Record<string, Handler> = {
    "GET accounts": { json: [ACCOUNT] },
    "GET accounts/acc-1/outreach-health": { json: HEALTH },
    "GET accounts/acc-2/outreach-health": { json: HEALTH },
    ...routes,
  };
  await page.route("**/api/v1/many/**", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const prefix = `/api/v1/many/orgs/${tenantId}/whatsapp/`;
    let path = url.pathname.startsWith(prefix)
      ? url.pathname.slice(prefix.length)
      : url.pathname;
    // `GET whatsapp/accounts` is the account list; routes below are keyed without the prefix.
    if (path === "" || path === "accounts/") path = "accounts";
    const raw: string | null = request.postData();
    let json: unknown = null;
    try {
      json = raw ? JSON.parse(raw) : null;
    } catch {
      json = null;
    }
    const call: Call = {
      method: request.method(),
      path,
      query: url.searchParams,
      raw,
      json,
    };
    calls.push(call);
    const handler = table[`${call.method} ${path}`];
    if (!handler) {
      return route.fulfill({
        status: 404,
        json: { error: { code: "NOT_FOUND", message: "no route" } },
      });
    }
    const reply = typeof handler === "function" ? handler(call) : handler;
    if (reply.status === 204) return route.fulfill({ status: 204 });
    return route.fulfill({
      status: reply.status ?? 200,
      json: reply.json ?? {},
    });
  });
  return {
    calls,
    find: (method: string, path: string) =>
      calls.filter((c) => c.method === method && c.path === path),
  };
}

async function asRole(page: Page, role: string) {
  await page.route("**/api/v1/tenants/*/summary", (route) =>
    route.fulfill({
      json: {
        organization_id: "x",
        organization_name: "Org",
        role,
        role_cap: null,
        via_agency: false,
      },
    }),
  );
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

test("a manager is refused the WhatsApp pages and no Many call is made", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-mgr");
  await asRole(page, "manager");
  const fake = await fakeMany(page, tenantId);
  await page.goto(`/app/${tenantId}/whatsapp/contacts`);
  await expect(page.getByTestId("page-forbidden")).toBeVisible();
  await expect(page.getByTestId("whatsapp-shell")).toHaveCount(0);
  expect(fake.calls).toHaveLength(0);
});

test("an agent and a viewer are refused too", async ({ page }) => {
  const { tenantId } = await registerAdmin(page, "P4C-agent");
  await asRole(page, "agent");
  const fake = await fakeMany(page, tenantId);
  await page.goto(`/app/${tenantId}/whatsapp/health`);
  await expect(page.getByTestId("page-forbidden")).toBeVisible();
  expect(fake.calls).toHaveLength(0);
});

test("the index redirects to contacts and the tab row links the sections", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-tabs");
  await fakeMany(page, tenantId, {
    "GET contacts": { json: { items: [CONTACT] } },
  });
  await page.goto(`/app/${tenantId}/whatsapp`);
  await expect(page).toHaveURL(/\/whatsapp\/contacts$/);
  const tabs = page.getByTestId("wa-tabs");
  for (const name of ["Contacts", "Templates", "Campaigns", "Health"]) {
    await expect(tabs.getByRole("link", { name })).toBeVisible();
  }
  await expect(page.getByTestId("wa-tab-contacts")).toHaveAttribute(
    "data-active",
    "true",
  );
});

test("no connected number shows one sentence and a link to channels", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-none");
  await fakeMany(page, tenantId, { "GET accounts": { json: [] } });
  await page.goto(`/app/${tenantId}/whatsapp/contacts`);
  const empty = page.getByTestId("page-empty");
  await expect(empty).toContainText("No WhatsApp number is connected");
  await expect(
    empty.getByRole("link", { name: "Open channels" }),
  ).toHaveAttribute("href", `/app/${tenantId}/channels`);
});

test("a 403 from Many is a forbidden state, a 502 retries and recovers", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-states");
  let attempt = 0;
  await fakeMany(page, tenantId, {
    "GET contacts": () => {
      attempt += 1;
      return attempt === 1
        ? {
            status: 502,
            json: { error: { code: "MANY_UNAVAILABLE", message: "down" } },
          }
        : { json: { items: [CONTACT] } };
    },
  });
  await page.goto(`/app/${tenantId}/whatsapp/contacts`);
  const state = page.getByTestId("page-unavailable");
  await expect(state).toBeVisible();
  await expect(state).not.toContainText("502");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("wa-contacts-table")).toContainText(
    "Dana Cohen",
  );
});

test("a 403 on the account list is the forbidden state", async ({ page }) => {
  const { tenantId } = await registerAdmin(page, "P4C-403");
  await fakeMany(page, tenantId, {
    "GET accounts": {
      status: 403,
      json: { error: { code: "FORBIDDEN", message: "no" } },
    },
  });
  await page.goto(`/app/${tenantId}/whatsapp/templates`);
  await expect(page.getByTestId("page-forbidden")).toBeVisible();
});

test("contacts: rows, an empty filter result, and the consent filter query", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-contacts");
  const fake = await fakeMany(page, tenantId, {
    "GET contacts": (call) =>
      call.query.get("consent") === "opted_out"
        ? { json: { items: [] } }
        : { json: { items: [CONTACT] } },
  });
  await page.goto(`/app/${tenantId}/whatsapp/contacts`);
  const table = page.getByTestId("wa-contacts-table");
  await expect(table).toContainText("Dana Cohen");
  await expect(table).toContainText("15550001111");
  await expect(table).toContainText("Inbound Message");
  expect(fake.find("GET", "contacts")[0].query.get("account_id")).toBe("acc-1");
  await page.getByTestId("wa-consent-filter").selectOption("opted_out");
  await expect(page.getByTestId("page-empty")).toContainText(
    "No contacts found",
  );
  expect(
    fake
      .find("GET", "contacts")
      .some((c) => c.query.get("consent") === "opted_out"),
  ).toBe(true);
});

test("contacts: the detail shows consent history; grant and revoke send the proof", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-consent");
  const fake = await fakeMany(page, tenantId, {
    "GET contacts": { json: { items: [CONTACT] } },
    "GET contacts/c-1": {
      json: {
        ...CONTACT,
        consent_history: [
          {
            id: "e-1",
            event_type: "opt_in_manual",
            source: "dashboard",
            evidence: { proof: "form on paper" },
            created_at: "2026-01-03T10:00:00Z",
          },
        ],
      },
    },
    "POST contacts/c-1/grant": { json: {} },
    "POST contacts/c-1/revoke": { json: {} },
  });
  await page.goto(`/app/${tenantId}/whatsapp/contacts`);
  await page.getByTestId("wa-contact-c-1").click();
  const dialog = page.getByTestId("wa-contact-dialog");
  await expect(dialog.getByTestId("wa-history")).toContainText("Opt In Manual");
  await expect(dialog.getByTestId("wa-history")).toContainText("form on paper");
  // A proof note is mandatory.
  await expect(dialog.getByTestId("wa-grant")).toBeDisabled();
  await dialog.getByLabel("Proof note").fill("Signed form, 3 Jan");
  await dialog.getByTestId("wa-grant").click();
  await expect
    .poll(() => fake.find("POST", "contacts/c-1/grant"))
    .toHaveLength(1);
  expect(fake.find("POST", "contacts/c-1/grant")[0].json).toEqual({
    proof: "Signed form, 3 Jan",
  });
  // The note is cleared once the grant is saved; write the next one after that.
  await expect(dialog.getByLabel("Proof note")).toHaveValue("");
  // Revoke asks first.
  await dialog.getByLabel("Proof note").fill("Asked to stop");
  await dialog.getByTestId("wa-revoke").click();
  expect(fake.find("POST", "contacts/c-1/revoke")).toHaveLength(0);
  await page
    .getByRole("dialog", { name: "Revoke permission?" })
    .getByRole("button", { name: "Revoke" })
    .click();
  await expect
    .poll(() => fake.find("POST", "contacts/c-1/revoke"))
    .toHaveLength(1);
  expect(fake.find("POST", "contacts/c-1/revoke")[0].json).toEqual({
    proof: "Asked to stop",
  });
});

test("contacts: the CSV import sends multipart with the attestation and refreshes", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-import");
  const fake = await fakeMany(page, tenantId, {
    "GET contacts": { json: { items: [CONTACT] } },
    "POST contacts/import": {
      json: { imported: 3, created: 2, deduplicated: 1, invalid: 0 },
    },
  });
  await page.goto(`/app/${tenantId}/whatsapp/contacts`);
  await page.getByTestId("wa-import-open").click();
  const dialog = page.getByTestId("wa-import-dialog");
  await dialog.getByTestId("wa-import-file").setInputFiles({
    name: "people.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("phone,name\n15550002222,Lee\n"),
  });
  // Not allowed until the attestation is ticked.
  await expect(dialog.getByTestId("wa-import-submit")).toBeDisabled();
  await dialog.getByTestId("wa-import-confirm").check();
  const before = fake.find("GET", "contacts").length;
  await dialog.getByTestId("wa-import-submit").click();
  await expect.poll(() => fake.find("POST", "contacts/import")).toHaveLength(1);
  const sent = fake.find("POST", "contacts/import")[0];
  expect(sent.raw).toContain('name="account_id"');
  expect(sent.raw).toContain("acc-1");
  expect(sent.raw).toContain(
    "I confirm these people gave permission to receive WhatsApp messages from this business",
  );
  expect(sent.raw).toContain('filename="people.csv"');
  expect(sent.raw).toContain("15550002222,Lee");
  await expect(page.getByText("Import complete: 3 imported")).toBeVisible();
  await expect
    .poll(() => fake.find("GET", "contacts").length)
    .toBeGreaterThan(before);
});

test("templates: list, create sends the body with examples, submit and sync", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-templates");
  const fake = await fakeMany(page, tenantId, {
    "GET templates": { json: [TEMPLATE, DRAFT] },
    "POST templates": { json: { ...DRAFT, id: "t-3" } },
    "POST templates/t-2/submit": { json: {} },
    "POST accounts/acc-1/templates/sync": { json: {} },
    "DELETE templates/t-2": { status: 204 },
  });
  await page.goto(`/app/${tenantId}/whatsapp/templates`);
  const list = page.getByTestId("wa-templates");
  await expect(list).toContainText("seasonal_offer");
  await expect(list).toContainText("Hello {{1}}, your offer is ready.");
  // Only an approved template can send a test; only a draft can be edited or submitted.
  await expect(page.getByTestId("wa-template-test")).toHaveCount(1);
  await expect(page.getByTestId("wa-template-submit")).toHaveCount(1);

  await page.getByTestId("wa-template-new").click();
  const dialog = page.getByTestId("wa-template-dialog");
  await dialog.getByTestId("wa-template-name").fill("New Offer!");
  await expect(dialog.getByTestId("wa-template-name")).toHaveValue(
    "new_offer_",
  );
  await dialog.getByTestId("wa-template-body").fill("Hi {{1}}, enjoy {{2}}");
  // Both placeholders need an example before the draft can be saved.
  await expect(dialog.getByTestId("wa-template-save")).toBeDisabled();
  await dialog.getByTestId("wa-example-1").fill("Sam");
  await dialog.getByTestId("wa-example-2").fill("10% off");
  await expect(dialog.getByTestId("wa-preview")).toHaveText(
    "Hi Sam, enjoy 10% off",
  );
  await dialog.getByTestId("wa-template-save").click();
  await expect.poll(() => fake.find("POST", "templates")).toHaveLength(1);
  expect(fake.find("POST", "templates")[0].json).toEqual({
    account_id: "acc-1",
    name: "new_offer_",
    language: "en_US",
    category: "marketing",
    components: [
      {
        type: "BODY",
        text: "Hi {{1}}, enjoy {{2}}",
        example: { body_text: ["Sam", "10% off"] },
      },
    ],
  });

  const loads = fake.find("GET", "templates").length;
  await page.getByTestId("wa-template-submit").click();
  await expect
    .poll(() => fake.find("POST", "templates/t-2/submit"))
    .toHaveLength(1);
  await expect
    .poll(() => fake.find("GET", "templates").length)
    .toBeGreaterThan(loads);

  await page.getByTestId("wa-sync").click();
  await expect
    .poll(() => fake.find("POST", "accounts/acc-1/templates/sync"))
    .toHaveLength(1);

  await page.getByTestId("wa-template-delete").click();
  expect(fake.find("DELETE", "templates/t-2")).toHaveLength(0);
  await page
    .getByRole("dialog", { name: "Delete this template?" })
    .getByRole("button", { name: "Delete" })
    .click();
  await expect.poll(() => fake.find("DELETE", "templates/t-2")).toHaveLength(1);
});

test("templates: empty state, and a Many error on submit is shown in plain words", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-tpl-err");
  let items: unknown[] = [];
  await fakeMany(page, tenantId, {
    "GET templates": () => ({ json: items }),
    "POST templates/t-2/submit": {
      status: 422,
      json: { detail: "Template body is too long" },
    },
  });
  await page.goto(`/app/${tenantId}/whatsapp/templates`);
  await expect(page.getByTestId("page-empty")).toContainText(
    "No templates yet",
  );
  items = [DRAFT];
  await page.reload();
  await page.getByTestId("wa-template-submit").click();
  await expect(
    page.locator('[role="alert"]:not(#__next-route-announcer__)'),
  ).toContainText("Template body is too long");
  await expect(
    page.locator('[role="alert"]:not(#__next-route-announcer__)'),
  ).not.toContainText("422");
});

test("templates: the test send grants consent first and posts the variables", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-testsend");
  const fake = await fakeMany(page, tenantId, {
    "GET templates": { json: [TEMPLATE] },
    "GET contacts": {
      json: { items: [{ ...CONTACT, marketing_consent: "opted_in" }] },
    },
    "POST contacts/c-1/grant": { json: {} },
    "POST templates/t-1/test-send": { json: { accepted: true } },
  });
  await page.goto(`/app/${tenantId}/whatsapp/templates`);
  await page.getByTestId("wa-template-test").click();
  const dialog = page.getByTestId("wa-test-dialog");
  await expect
    .poll(() => fake.find("GET", "contacts")[0]?.query.get("consent"))
    .toBe("opted_in");
  await expect(dialog.getByTestId("wa-test-send")).toBeDisabled();
  await dialog.getByLabel("Manual grant proof note").fill("My own number");
  await dialog.getByTestId("wa-test-grant").click();
  await expect
    .poll(() => fake.find("POST", "contacts/c-1/grant"))
    .toHaveLength(1);
  expect(fake.find("POST", "contacts/c-1/grant")[0].json).toEqual({
    proof: "My own number",
  });
  await dialog.getByTestId("wa-test-value-1").fill("Sam");
  await dialog.getByTestId("wa-test-send").click();
  await expect
    .poll(() => fake.find("POST", "templates/t-1/test-send"))
    .toHaveLength(1);
  expect(fake.find("POST", "templates/t-1/test-send")[0].json).toEqual({
    contact_id: "c-1",
    variables: { "1": "Sam" },
  });
});

test("campaigns: list shows template names and links to the detail", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-camp-list");
  await fakeMany(page, tenantId, {
    "GET campaigns": { json: [CAMPAIGN] },
    "GET templates": { json: [TEMPLATE] },
  });
  await page.goto(`/app/${tenantId}/whatsapp/campaigns`);
  const table = page.getByTestId("wa-campaigns-table");
  await expect(table).toContainText("Spring push");
  await expect(table).toContainText("seasonal_offer");
  await expect(table).toContainText("4 sent · 1 failed · 2 skipped");
  await expect(page.getByTestId("wa-campaign-cp-1")).toHaveAttribute(
    "href",
    `/app/${tenantId}/whatsapp/campaigns/cp-1`,
  );
});

test("campaigns: an empty list says so", async ({ page }) => {
  const { tenantId } = await registerAdmin(page, "P4C-camp-empty");
  await fakeMany(page, tenantId, {
    "GET campaigns": { json: [] },
    "GET templates": { json: [] },
  });
  await page.goto(`/app/${tenantId}/whatsapp/campaigns`);
  await expect(page.getByTestId("page-empty")).toContainText(
    "No campaigns yet",
  );
});

test("new campaign: template, audience, variables, dry-run, then start", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-wizard");
  const fake = await fakeMany(page, tenantId, {
    "GET templates": {
      json: [
        TEMPLATE,
        { ...TEMPLATE, id: "t-auth", name: "otp", category: "authentication" },
      ],
    },
    "GET contacts": { json: { items: [CONTACT, { ...CONTACT, id: "c-2" }] } },
    "POST campaigns": { json: { ...CAMPAIGN, status: "draft" } },
    "POST campaigns/cp-1/dry-run": {
      json: {
        eligible: 7,
        terminal_skips: { count: 2, reasons: { opted_out: 2 } },
        deferrable_blocks: { count: 1, reasons: { daily_cap_reached: 1 } },
        estimated_days_to_finish: 1,
        daily_cap: 250,
        used_in_rolling_24h: 5,
      },
    },
    "POST campaigns/cp-1/start": { json: {} },
    "GET campaigns/cp-1/stats": { json: STATS() },
  });
  await page.goto(`/app/${tenantId}/whatsapp/campaigns/new`);
  await expect(page.getByTestId("wa-new-template")).toBeVisible();
  const prep = fake.find("GET", "templates")[0];
  expect(prep.query.get("template_status")).toBe("approved");
  // Authentication templates are not offered.
  await expect(page.getByTestId("wa-new-template")).not.toContainText("otp");
  await page.getByTestId("wa-new-name").fill("Spring push");
  await page.getByTestId("wa-next").click();
  await expect(page.getByText("2 contacts currently loaded")).toBeVisible();
  await page.getByTestId("wa-next").click();
  await expect(page.getByTestId("wa-dry-run")).toBeDisabled();
  await page.getByTestId("wa-map-value-1").fill("friend");
  await page.getByTestId("wa-dry-run").click();
  await expect(page.getByTestId("wa-dry-result")).toContainText("7");
  await expect(page.getByTestId("wa-dry-result")).toContainText("Opted out");
  await expect(page.getByTestId("wa-dry-result")).toContainText(
    "Daily sending cap reached",
  );
  const mapping = { "1": { source: "literal", value: "friend" } };
  expect(fake.find("POST", "campaigns")[0].json).toEqual({
    account_id: "acc-1",
    template_id: "t-1",
    name: "Spring push",
    throttle_per_minute: 30,
    variable_mapping: mapping,
  });
  expect(fake.find("POST", "campaigns/cp-1/dry-run")[0].json).toEqual({
    variable_mapping: mapping,
  });
  await page.getByTestId("wa-next").click();
  // Start only after the person says they reviewed the dry-run.
  await expect(page.getByTestId("wa-start")).toBeDisabled();
  expect(fake.find("POST", "campaigns/cp-1/start")).toHaveLength(0);
  await page.getByTestId("wa-reviewed").check();
  await page.getByTestId("wa-start").click();
  await expect
    .poll(() => fake.find("POST", "campaigns/cp-1/start"))
    .toHaveLength(1);
  await expect(page).toHaveURL(/\/whatsapp\/campaigns\/cp-1$/);
});

test("campaign detail: stats, unknown outcomes, pause and a confirmed cancel", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-detail");
  const fake = await fakeMany(page, tenantId, {
    "GET campaigns/cp-1/stats": { json: STATS() },
    "POST campaigns/cp-1/pause": { json: {} },
    "POST campaigns/cp-1/cancel": { json: {} },
  });
  await page.goto(`/app/${tenantId}/whatsapp/campaigns/cp-1`);
  const detail = page.getByTestId("wa-campaign-detail");
  await expect(detail).toContainText("Spring push");
  await expect(page.getByTestId("wa-metrics")).toContainText("Delivered");
  await expect(page.getByTestId("wa-unknown")).toContainText("1");
  await expect(page.getByTestId("wa-reasons")).toContainText(
    "No marketing permission",
  );
  await page.getByTestId("wa-pause").click();
  await expect
    .poll(() => fake.find("POST", "campaigns/cp-1/pause"))
    .toHaveLength(1);
  await page.getByTestId("wa-cancel").click();
  expect(fake.find("POST", "campaigns/cp-1/cancel")).toHaveLength(0);
  await page
    .getByRole("dialog", { name: "Cancel this campaign?" })
    .getByRole("button", { name: "Cancel campaign" })
    .click();
  await expect
    .poll(() => fake.find("POST", "campaigns/cp-1/cancel"))
    .toHaveLength(1);
});

test("campaign detail: resume needs a note and sends it", async ({ page }) => {
  const { tenantId } = await registerAdmin(page, "P4C-resume");
  const fake = await fakeMany(page, tenantId, {
    "GET campaigns/cp-1/stats": {
      json: STATS({ ...CAMPAIGN, status: "paused" }),
    },
    "POST campaigns/cp-1/resume": { json: {} },
  });
  await page.goto(`/app/${tenantId}/whatsapp/campaigns/cp-1`);
  await expect(page.getByTestId("wa-resume")).toBeDisabled();
  await page.getByTestId("wa-resume-note").fill("Quality is green again");
  await page.getByTestId("wa-resume").click();
  await expect
    .poll(() => fake.find("POST", "campaigns/cp-1/resume"))
    .toHaveLength(1);
  expect(fake.find("POST", "campaigns/cp-1/resume")[0].json).toEqual({
    note: "Quality is green again",
  });
});

test("campaign detail: a 404 is the not-available state", async ({ page }) => {
  const { tenantId } = await registerAdmin(page, "P4C-detail-404");
  await fakeMany(page, tenantId, {
    "GET campaigns/nope/stats": {
      status: 404,
      json: { detail: "Not found" },
    },
  });
  await page.goto(`/app/${tenantId}/whatsapp/campaigns/nope`);
  await expect(page.getByTestId("page-not_available")).toBeVisible();
});

test("health: figures, save sends the keyword lists and cap, then refreshes", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-health");
  const fake = await fakeMany(page, tenantId, {
    "PATCH accounts/acc-1/outreach-settings": { json: {} },
    "POST accounts/acc-1/health-refresh": { json: {} },
  });
  await page.goto(`/app/${tenantId}/whatsapp/health`);
  const health = page.getByTestId("wa-health");
  await expect(health).toContainText("GREEN");
  await expect(health).toContainText("TIER_1K");
  await expect(health).toContainText("5 / 250");
  await expect(health).toContainText("Fresh");
  await expect(page.getByTestId("wa-opt-in")).toHaveValue("START");

  await page.getByTestId("wa-opt-in").fill("START, YES ,");
  await page.getByTestId("wa-cap").fill("400");
  await page.getByTestId("wa-ctwa").locator("input").check();
  const before = fake.find("GET", "accounts/acc-1/outreach-health").length;
  await page.getByTestId("wa-settings-save").click();
  await expect
    .poll(() => fake.find("PATCH", "accounts/acc-1/outreach-settings"))
    .toHaveLength(1);
  expect(
    fake.find("PATCH", "accounts/acc-1/outreach-settings")[0].json,
  ).toEqual({
    ctwa_counts_as_consent: true,
    transactional_utility_attested: false,
    opt_in_keywords: ["START", "YES"],
    opt_out_keywords: ["STOP"],
    outreach_daily_cap: 400,
  });
  await expect
    .poll(() => fake.find("GET", "accounts/acc-1/outreach-health").length)
    .toBeGreaterThan(before);

  await page.getByTestId("wa-health-refresh").click();
  await expect
    .poll(() => fake.find("POST", "accounts/acc-1/health-refresh"))
    .toHaveLength(1);
});

test("health: the opt-in link, and rotating asks before it revokes older links", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-optin");
  const fake = await fakeMany(page, tenantId, {
    "POST accounts/acc-1/opt-in-link": (call) => ({
      json: {
        url: "https://example.test/optin/abc",
        expires_at: "2026-02-01T00:00:00Z",
        older_links_revoked: (call.json as { rotate: boolean }).rotate,
      },
    }),
  });
  await page.goto(`/app/${tenantId}/whatsapp/health`);
  await page.getByTestId("wa-optin-get").click();
  await expect(page.getByTestId("wa-optin-result")).toContainText(
    "https://example.test/optin/abc",
  );
  expect(fake.find("POST", "accounts/acc-1/opt-in-link")[0].json).toEqual({
    rotate: false,
  });
  await page.getByTestId("wa-rotate").check();
  await page.getByTestId("wa-optin-rotate").click();
  expect(fake.find("POST", "accounts/acc-1/opt-in-link")).toHaveLength(1);
  await page
    .getByRole("dialog", { name: "Revoke every older opt-in link?" })
    .getByRole("button", { name: "Rotate and create link" })
    .click();
  await expect
    .poll(() => fake.find("POST", "accounts/acc-1/opt-in-link"))
    .toHaveLength(2);
  expect(fake.find("POST", "accounts/acc-1/opt-in-link")[1].json).toEqual({
    rotate: true,
  });
});

test("health: a global kill switch shows the banner and blocks starting", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-killswitch");
  await fakeMany(page, tenantId, {
    "GET accounts/acc-1/outreach-health": {
      json: { ...HEALTH, outreach_enabled: false },
    },
    "GET campaigns": { json: [] },
    "GET templates": { json: [] },
  });
  await page.goto(`/app/${tenantId}/whatsapp/campaigns`);
  await expect(page.getByTestId("wa-disabled")).toContainText(
    "disabled globally",
  );
  await expect(
    page.getByRole("button", { name: "New campaign" }),
  ).toBeDisabled();
});

test("a paused account offers the resume dialog and posts the note", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-paused");
  const fake = await fakeMany(page, tenantId, {
    "GET accounts/acc-1/outreach-health": {
      json: {
        ...HEALTH,
        outreach_paused: true,
        outreach_paused_reason: "Quality turned red",
      },
    },
    "GET contacts": { json: { items: [CONTACT] } },
    "GET campaigns": () => ({ json: [{ ...CAMPAIGN, status: "paused" }] }),
    "POST campaigns/cp-1/resume": { json: {} },
  });
  await page.goto(`/app/${tenantId}/whatsapp/contacts`);
  await expect(page.getByTestId("wa-paused")).toContainText(
    "Quality turned red",
  );
  await page.getByTestId("wa-resume-open").click();
  const dialog = page.getByTestId("wa-resume-dialog");
  await expect
    .poll(() =>
      fake
        .find("GET", "campaigns")
        .some((c) => c.query.get("campaign_status") === "paused"),
    )
    .toBe(true);
  await expect(dialog.getByTestId("wa-resume-submit")).toBeDisabled();
  await dialog.getByLabel("Required resume note").fill("Checked with Meta");
  await dialog.getByTestId("wa-resume-submit").click();
  await expect
    .poll(() => fake.find("POST", "campaigns/cp-1/resume"))
    .toHaveLength(1);
  expect(fake.find("POST", "campaigns/cp-1/resume")[0].json).toEqual({
    note: "Checked with Meta",
  });
});

test("switching the number reloads the page for that account", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4C-switch");
  const fake = await fakeMany(page, tenantId, {
    "GET accounts": { json: [ACCOUNT, ACCOUNT_2] },
    "GET contacts": (call) => ({
      json: {
        items: [
          {
            ...CONTACT,
            display_name:
              call.query.get("account_id") === "acc-2"
                ? "Second Number"
                : "Dana Cohen",
          },
        ],
      },
    }),
  });
  await page.goto(`/app/${tenantId}/whatsapp/contacts`);
  await expect(page.getByTestId("wa-contacts-table")).toContainText(
    "Dana Cohen",
  );
  await page.getByTestId("wa-account-select").selectOption("acc-2");
  await expect(page.getByTestId("wa-contacts-table")).toContainText(
    "Second Number",
  );
  expect(
    fake
      .find("GET", "contacts")
      .some((c) => c.query.get("account_id") === "acc-2"),
  ).toBe(true);
});
