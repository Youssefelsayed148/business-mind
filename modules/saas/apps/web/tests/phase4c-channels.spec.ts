import { expect, test, type Page, type Route } from "@playwright/test";

import { registerAdmin, uniqueEmail } from "./e2e-helpers";

/**
 * Phase 4C: Facebook and WhatsApp channels page, Facebook campaigns page and the /accounts
 * return address. The browser's calls to /api/v1/many/orgs/... are answered by Playwright
 * (no Many process here); sign-in is the real API. The role comes from a mocked
 * /tenants/{id}/summary. The Meta SDK script is replaced by a stub: the real Meta popup
 * cannot be driven from here.
 */

type Call = { method: string; path: string; body: unknown };
type Handler = (call: Call) => { status?: number; json?: unknown };

const PAGE_ONE = {
  id: "p1",
  page_id: "1001",
  page_name: "Café Page",
  status: "connected",
  ai_enabled: false,
  ai_cold_dm_enabled: false,
  business_vertical: "general",
  ai_daily_message_cap: 100,
  ai_messages_sent_today: 3,
  updated_at: "2026-01-02T10:00:00Z",
};
const NUMBER_ONE = {
  id: "w1",
  phone_number_id: "555",
  display_phone_number: "+1 555 0100",
  status: "connected",
  ai_enabled: true,
  business_vertical: "general",
  ai_daily_message_cap: 50,
  ai_messages_sent_today: 0,
  updated_at: "2026-01-03T10:00:00Z",
};
const CAMPAIGN = {
  id: "c1",
  facebook_page_id: "p1",
  name: "Summer promo",
  match_type: "contains",
  message_template: "Hello!",
  cooldown_hours: 168,
  status: "active",
  comment_reply_enabled: false,
  ai_enabled: false,
  total_triggers: 7,
  keywords: [{ id: "k1", normalized_keyword: "promo" }],
};
const DELEGATION = {
  saas_delegation_enabled: false,
  saas_connection_id: null,
  saas_base_url: null,
  secret_set: false,
  previous_secret_active: false,
  previous_secret_expires_at: null,
  last_forward_status: null,
  last_forward_at: null,
  queue_depth: null,
  failed_events: null,
  retryable_failed_events: null,
  degraded: false,
};

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

async function mockRole(page: Page, tenantId: string, role: string) {
  await page.route(`**/api/v1/tenants/${tenantId}/summary`, (route) =>
    route.fulfill({
      json: {
        organization_id: tenantId,
        organization_name: "Org",
        role,
        role_cap: null,
        via_agency: false,
      },
    }),
  );
}

/** Answers every Many call of an organization; unknown calls are recorded and get a 404. */
async function mockMany(
  page: Page,
  tenantId: string,
  handlers: Record<string, Handler>,
) {
  const calls: Call[] = [];
  const unexpected: string[] = [];
  await page.route(`**/api/v1/many/orgs/${tenantId}/**`, (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.split(`/many/orgs/${tenantId}/`)[1];
    const raw = request.postData();
    const call: Call = {
      method: request.method(),
      path,
      body: raw ? JSON.parse(raw) : undefined,
    };
    calls.push(call);
    const handler = handlers[`${call.method} ${path}`];
    if (!handler) {
      unexpected.push(`${call.method} ${path}`);
      return route.fulfill({
        status: 404,
        json: { error: { code: "NOT_FOUND", message: "no" } },
      });
    }
    const answer = handler(call);
    return route.fulfill({
      status: answer.status ?? 200,
      json: answer.json ?? {},
    });
  });
  return {
    calls,
    unexpected,
    count: (method: string, path: string) =>
      calls.filter((c) => c.method === method && c.path === path).length,
    last: (method: string, path: string) =>
      [...calls].reverse().find((c) => c.method === method && c.path === path),
  };
}

const channelHandlers = (): Record<string, Handler> => ({
  "GET whatsapp/accounts": () => ({ json: [NUMBER_ONE] }),
  "GET facebook/accounts": () => ({ json: [PAGE_ONE] }),
  "GET facebook/accounts/p1/saas-delegation": () => ({ json: DELEGATION }),
  "GET whatsapp/accounts/w1/saas-delegation": () => ({ json: DELEGATION }),
});

async function signIn(page: Page, role: string) {
  const { tenantId } = await registerAdmin(page, "p4c", {
    email: uniqueEmail("p4c"),
  });
  await mockRole(page, tenantId, role);
  return tenantId;
}

// ---------------------------------------------------------------- channels page

test("channels page lists Facebook Pages and WhatsApp numbers with their status", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  const many = await mockMany(page, tenantId, channelHandlers());
  await page.goto(`/app/${tenantId}/channels`);
  await expect(page.getByTestId("account-facebook-p1")).toContainText(
    "Café Page",
  );
  await expect(page.getByTestId("account-whatsapp-w1")).toContainText(
    "+1 555 0100",
  );
  await expect(page.getByTestId("account-whatsapp-w1")).toContainText(
    "connected",
  );
  expect(many.count("GET", "facebook/accounts")).toBe(1);
  expect(many.count("GET", "whatsapp/accounts")).toBe(1);
  // No Instagram on this page.
  await expect(page.getByText(/instagram/i)).toHaveCount(0);
});

test("channels page: both lists empty shows one sentence and a connect action for an admin", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  await mockMany(page, tenantId, {
    "GET whatsapp/accounts": () => ({ json: [] }),
    "GET facebook/accounts": () => ({ json: [] }),
  });
  await page.goto(`/app/${tenantId}/channels`);
  await expect(page.getByTestId("empty-facebook")).toContainText(
    "No Facebook Pages connected yet.",
  );
  await expect(page.getByTestId("empty-whatsapp")).toContainText(
    "No WhatsApp numbers connected yet.",
  );
  await expect(page.getByTestId("connect-facebook")).toBeVisible();
  await expect(page.getByTestId("connect-whatsapp")).toBeVisible();
});

test("channels page: a 403 is the forbidden state, a 502 can be retried", async ({
  page,
}) => {
  const tenantId = await signIn(page, "viewer");
  let status = 403;
  await mockMany(page, tenantId, {
    "GET whatsapp/accounts": () => ({
      status,
      json: { error: { code: "FORBIDDEN", message: "no" } },
    }),
    "GET facebook/accounts": () => ({ json: [PAGE_ONE] }),
  });
  await page.goto(`/app/${tenantId}/channels`);
  await expect(page.getByTestId("page-forbidden")).toBeVisible();
  await expect(page.getByTestId("page-forbidden")).not.toContainText("403");
  status = 502;
  await page.reload();
  const failed = page.getByTestId("page-unavailable");
  await expect(failed).toBeVisible();
  status = 200;
  // A good answer after the retry shows the page.
  await page.unroute(`**/api/v1/many/orgs/${tenantId}/**`);
  await mockMany(page, tenantId, channelHandlers());
  await failed.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("channels-page")).toBeVisible();
});

for (const role of ["viewer", "agent", "manager"]) {
  test(`${role} reads the channels page but cannot connect, disconnect or delete`, async ({
    page,
  }) => {
    const tenantId = await signIn(page, role);
    const many = await mockMany(page, tenantId, channelHandlers());
    await page.goto(`/app/${tenantId}/channels`);
    await expect(page.getByTestId("account-facebook-p1")).toBeVisible();
    await expect(page.getByTestId("connect-facebook")).toHaveCount(0);
    await expect(page.getByTestId("connect-whatsapp")).toHaveCount(0);
    await expect(page.getByTestId("disconnect-p1")).toHaveCount(0);
    await expect(page.getByTestId("hard-delete-p1")).toHaveCount(0);
    // AI settings can be read, not changed; the delegation panel is not shown at all.
    await page.getByTestId("toggle-ai-p1").click();
    await expect(page.getByTestId("ai-settings-p1")).toBeVisible();
    await expect(
      page.getByTestId("ai-settings-p1").getByLabel("Daily message cap"),
    ).toBeDisabled();
    await expect(page.getByTestId("save-ai-settings")).toHaveCount(0);
    await expect(page.getByTestId("delegation-p1")).toHaveCount(0);
    expect(many.count("GET", "facebook/accounts/p1/saas-delegation")).toBe(0);
  });
}

test("admin disconnects a Page after confirming (DELETE, then the list reloads); no hard delete", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  const many = await mockMany(page, tenantId, {
    ...channelHandlers(),
    "DELETE facebook/accounts/p1": () => ({ json: {} }),
  });
  await page.goto(`/app/${tenantId}/channels`);
  await expect(page.getByTestId("hard-delete-p1")).toHaveCount(0);
  await page.getByTestId("disconnect-p1").click();
  expect(many.count("DELETE", "facebook/accounts/p1")).toBe(0);
  await page
    .locator("dialog[open]")
    .getByRole("button", { name: "Disconnect", exact: true })
    .click();
  await expect(page.getByTestId("channels-note")).toContainText(
    "Facebook Page disconnected.",
  );
  expect(many.count("DELETE", "facebook/accounts/p1")).toBe(1);
  expect(many.count("GET", "facebook/accounts")).toBe(2);
});

test("owner hard-deletes a WhatsApp number (DELETE .../hard)", async ({
  page,
}) => {
  const tenantId = await signIn(page, "owner");
  const many = await mockMany(page, tenantId, {
    ...channelHandlers(),
    "DELETE whatsapp/accounts/w1/hard": () => ({ json: {} }),
  });
  await page.goto(`/app/${tenantId}/channels`);
  await page.getByTestId("hard-delete-w1").click();
  await page
    .locator("dialog[open]")
    .getByRole("button", { name: "Delete permanently" })
    .click();
  await expect(page.getByTestId("channels-note")).toContainText(
    "permanently deleted",
  );
  expect(many.count("DELETE", "whatsapp/accounts/w1/hard")).toBe(1);
  expect(many.count("GET", "whatsapp/accounts")).toBe(2);
});

test("a failed disconnect shows the plain message and keeps the list", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  await mockMany(page, tenantId, {
    ...channelHandlers(),
    "DELETE facebook/accounts/p1": () => ({
      status: 409,
      json: { detail: "Page has running campaigns." },
    }),
  });
  await page.goto(`/app/${tenantId}/channels`);
  await page.getByTestId("disconnect-p1").click();
  await page
    .locator("dialog[open]")
    .getByRole("button", { name: "Disconnect", exact: true })
    .click();
  await expect(page.getByTestId("channels-note")).toContainText(
    "Page has running campaigns.",
  );
  await expect(page.getByTestId("channels-note")).not.toContainText("409");
  await expect(page.getByTestId("account-facebook-p1")).toBeVisible();
});

test("admin saves AI settings with the right PATCH body, and the list reloads", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  const many = await mockMany(page, tenantId, {
    ...channelHandlers(),
    "PATCH facebook/accounts/p1/ai-settings": () => ({ json: PAGE_ONE }),
  });
  await page.goto(`/app/${tenantId}/channels`);
  await page.getByTestId("toggle-ai-p1").click();
  const panel = page.getByTestId("ai-settings-p1");
  await panel.getByLabel("Enabled").check();
  await panel.getByLabel("Business vertical").selectOption("restaurant");
  await panel.getByLabel("Daily message cap").fill("250");
  await panel.getByLabel("Business profile").fill("Open daily 9 to 5.");
  await page.getByTestId("save-ai-settings").click();
  await expect(page.getByTestId("channels-note")).toContainText(
    "AI settings saved.",
  );
  expect(many.last("PATCH", "facebook/accounts/p1/ai-settings")?.body).toEqual({
    business_vertical: "restaurant",
    ai_enabled: true,
    ai_cold_dm_enabled: false,
    ai_business_profile: "Open daily 9 to 5.",
    ai_tone_instructions: "",
    ai_daily_message_cap: 250,
  });
  expect(many.count("GET", "facebook/accounts")).toBe(2);
});

test("WhatsApp AI settings have no unsolicited-message option and omit it from the body", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  const many = await mockMany(page, tenantId, {
    ...channelHandlers(),
    "PATCH whatsapp/accounts/w1/ai-settings": () => ({ json: NUMBER_ONE }),
  });
  await page.goto(`/app/${tenantId}/channels`);
  await page.getByTestId("toggle-ai-w1").click();
  await expect(page.getByTestId("ai-settings-w1")).not.toContainText(
    "unsolicited",
  );
  await page.getByTestId("save-ai-settings").click();
  await expect(page.getByTestId("channels-note")).toContainText("saved");
  const body = many.last("PATCH", "whatsapp/accounts/w1/ai-settings")
    ?.body as Record<string, unknown>;
  expect(body).not.toHaveProperty("ai_cold_dm_enabled");
  expect(body.ai_enabled).toBe(true);
});

test("delegation panel (admin): enable sends the connection, URL and secret to PATCH", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  const many = await mockMany(page, tenantId, {
    ...channelHandlers(),
    "PATCH facebook/accounts/p1/saas-delegation": () => ({
      json: { ...DELEGATION, saas_delegation_enabled: true, secret_set: true },
    }),
  });
  await page.goto(`/app/${tenantId}/channels`);
  await page.getByTestId("toggle-ai-p1").click();
  const panel = page.getByTestId("delegation-p1");
  await expect(panel).toBeVisible();
  await panel.getByLabel("Connection ID").fill("conn-1");
  await panel.getByLabel("SaaS base URL").fill("https://saas.example.com");
  await panel.getByLabel("Signing secret").fill("s".repeat(40));
  await page.getByTestId("delegation-enable").click();
  await expect(page.getByTestId("channels-note")).toContainText(
    "Delegation enabled.",
  );
  expect(
    many.last("PATCH", "facebook/accounts/p1/saas-delegation")?.body,
  ).toEqual({
    saas_connection_id: "conn-1",
    saas_base_url: "https://saas.example.com",
    secret: "s".repeat(40),
    saas_delegation_enabled: true,
  });
  // The secret is never shown again; the next view starts empty.
  await expect(panel.getByLabel("Signing secret")).toHaveValue("");
  await expect(page.getByTestId("delegation-disable")).toBeVisible();
});

// ------------------------------------------------------------ connect and Meta SDK

function sdkStub(loginResponse: unknown) {
  return `window.FB = { init: function () {}, login: function (cb, options) { window.__fbLoginOptions = options; cb(${JSON.stringify(loginResponse)}); } };
if (window.fbAsyncInit) window.fbAsyncInit();`;
}

test("Facebook connect: the Meta SDK loads only on click; the token and state go to the callback", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  const sdkHits: string[] = [];
  await page.route("https://connect.facebook.net/**", (route) => {
    sdkHits.push(route.request().url());
    return route.fulfill({
      contentType: "application/javascript",
      body: sdkStub({
        status: "connected",
        authResponse: { accessToken: "tok-123" },
      }),
    });
  });
  let pages = [] as unknown[];
  const many = await mockMany(page, tenantId, {
    "GET whatsapp/accounts": () => ({ json: [] }),
    "GET facebook/accounts": () => ({ json: pages }),
    "GET facebook/connect/start": () => ({
      json: {
        app_id: "APP-FROM-API",
        config_id: "cfg-9",
        graph_api_version: "v21.0",
        state: "state-7",
      },
    }),
    "POST facebook/connect/callback": () => {
      pages = [PAGE_ONE];
      return {
        json: {
          connected: [{ page_id: "1001", page_name: "Café Page" }],
          conflicts: [{ page_id: "2002" }],
        },
      };
    },
  });
  await page.goto(`/app/${tenantId}/channels`);
  await expect(page.getByTestId("connect-facebook")).toBeVisible();
  expect(sdkHits).toHaveLength(0);
  expect(many.count("GET", "facebook/connect/start")).toBe(0);

  await page.getByTestId("connect-facebook").click();
  await expect(page.getByTestId("channels-note")).toContainText(
    "Facebook Page connected.",
  );
  await expect(page.getByTestId("channels-note")).toContainText(
    "already connected to a different workspace",
  );
  expect(sdkHits).toHaveLength(1);
  expect(many.last("POST", "facebook/connect/callback")?.body).toEqual({
    access_token: "tok-123",
    state: "state-7",
  });
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { __fbLoginOptions: unknown }).__fbLoginOptions,
    ),
  ).toEqual({ config_id: "cfg-9" });
  await expect(page.getByTestId("account-facebook-p1")).toBeVisible();
});

test("Facebook connect: a cancelled login shows a plain message and posts nothing", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  await page.route("https://connect.facebook.net/**", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: sdkStub({ status: "unknown", authResponse: null }),
    }),
  );
  const many = await mockMany(page, tenantId, {
    "GET whatsapp/accounts": () => ({ json: [] }),
    "GET facebook/accounts": () => ({ json: [] }),
    "GET facebook/connect/start": () => ({
      json: {
        app_id: "A",
        config_id: "c",
        graph_api_version: "v21.0",
        state: "s",
      },
    }),
  });
  await page.goto(`/app/${tenantId}/channels`);
  await page.getByTestId("connect-facebook").first().click();
  await expect(page.getByTestId("channels-note")).toContainText(
    "cancelled or did not complete",
  );
  expect(many.count("POST", "facebook/connect/callback")).toBe(0);
});

test("WhatsApp connect: without the signup details from Meta nothing is posted", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  await page.route("https://connect.facebook.net/**", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      // A code, but no WA_EMBEDDED_SIGNUP message from facebook.com (a page cannot forge one).
      body: sdkStub({ status: "connected", authResponse: { code: "code-1" } }),
    }),
  );
  const many = await mockMany(page, tenantId, {
    "GET whatsapp/accounts": () => ({ json: [] }),
    "GET facebook/accounts": () => ({ json: [] }),
    "GET whatsapp/connect/start": () => ({
      json: {
        app_id: "A",
        config_id: "wa-cfg",
        graph_api_version: "v21.0",
        state: "s",
      },
    }),
  });
  await page.goto(`/app/${tenantId}/channels`);
  await page.getByTestId("connect-whatsapp").first().click();
  await expect(page.getByTestId("channels-note")).toContainText(
    "Did not receive the phone number details",
  );
  expect(many.count("POST", "whatsapp/connect/callback")).toBe(0);
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { __fbLoginOptions: unknown }).__fbLoginOptions,
    ),
  ).toEqual({
    config_id: "wa-cfg",
    response_type: "code",
    override_default_response_type: true,
  });
});

// ---------------------------------------------------------- Facebook campaigns

const campaignHandlers = (): Record<string, Handler> => ({
  "GET facebook/campaigns": () => ({ json: [CAMPAIGN] }),
  "GET facebook/accounts": () => ({ json: [PAGE_ONE] }),
});

test("campaigns page lists campaigns with Page name, keywords, status and triggers", async ({
  page,
}) => {
  const tenantId = await signIn(page, "viewer");
  await mockMany(page, tenantId, campaignHandlers());
  await page.goto(`/app/${tenantId}/facebook/campaigns`);
  const table = page.getByTestId("campaigns-page");
  await expect(table).toContainText("Summer promo");
  await expect(table).toContainText("Café Page");
  await expect(table).toContainText("promo");
  await expect(table).toContainText("7");
  // A viewer reads only.
  await expect(page.getByTestId("new-campaign")).toHaveCount(0);
  await expect(page.getByTestId("edit-c1")).toHaveCount(0);
  await expect(page.getByTestId("delete-c1")).toHaveCount(0);
  await expect(page.getByTestId("toggle-status-c1")).toHaveCount(0);
});

test("campaigns page: no Pages, no campaigns, 403 and 502 states", async ({
  page,
}) => {
  const tenantId = await signIn(page, "manager");
  let mode: "nopages" | "empty" | "403" | "502" = "nopages";
  await mockMany(page, tenantId, {
    "GET facebook/campaigns": () =>
      mode === "403"
        ? { status: 403, json: { error: { code: "FORBIDDEN", message: "no" } } }
        : mode === "502"
          ? {
              status: 502,
              json: { error: { code: "MANY_UNAVAILABLE", message: "down" } },
            }
          : { json: [] },
    "GET facebook/accounts": () => ({
      json: mode === "nopages" ? [] : [PAGE_ONE],
    }),
  });
  await page.goto(`/app/${tenantId}/facebook/campaigns`);
  await expect(page.getByTestId("campaigns-no-pages")).toContainText(
    "No Facebook Pages connected yet.",
  );
  await expect(page.getByTestId("new-campaign")).toHaveCount(0);
  mode = "empty";
  await page.reload();
  await expect(page.getByTestId("campaigns-empty")).toContainText(
    "No campaigns yet.",
  );
  await expect(page.getByTestId("new-campaign")).toBeVisible();
  mode = "403";
  await page.reload();
  await expect(page.getByTestId("page-forbidden")).toBeVisible();
  await expect(page.getByTestId("page-forbidden")).not.toContainText("403");
  mode = "502";
  await page.reload();
  await expect(page.getByTestId("page-unavailable")).toBeVisible();
  mode = "empty";
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("campaigns-empty")).toBeVisible();
});

test("manager creates a campaign: POST body has the Page, fields and keywords; the list reloads", async ({
  page,
}) => {
  const tenantId = await signIn(page, "manager");
  const many = await mockMany(page, tenantId, {
    ...campaignHandlers(),
    "POST facebook/campaigns": () => ({ json: { ...CAMPAIGN, id: "c2" } }),
  });
  await page.goto(`/app/${tenantId}/facebook/campaigns`);
  await page.getByTestId("new-campaign").click();
  const form = page.getByTestId("campaign-form");
  await form.getByLabel("Campaign name").fill("Winter sale");
  await form
    .getByLabel("Trigger keywords (comma-separated)")
    .fill("Promo, PRICE ,,");
  await form.getByLabel("Private reply message").fill("Thanks for asking!");
  await page.getByTestId("save-campaign").click();
  await expect(page.getByTestId("campaign-form")).toHaveCount(0);
  expect(many.last("POST", "facebook/campaigns")?.body).toEqual({
    facebook_page_id: "p1",
    name: "Winter sale",
    match_type: "contains",
    message_template: "Thanks for asking!",
    target_scope: "any_post",
    target_post_id: null,
    cooldown_hours: 168,
    comment_reply_enabled: false,
    comment_reply_text: null,
    ai_enabled: false,
    keywords: ["promo", "price"],
  });
  expect(many.count("GET", "facebook/campaigns")).toBe(2);
});

test("a failed save keeps the form open and shows the plain message", async ({
  page,
}) => {
  const tenantId = await signIn(page, "manager");
  await mockMany(page, tenantId, {
    ...campaignHandlers(),
    "POST facebook/campaigns": () => ({
      status: 422,
      json: { detail: "Name is too long." },
    }),
  });
  await page.goto(`/app/${tenantId}/facebook/campaigns`);
  await page.getByTestId("new-campaign").click();
  await page.getByLabel("Campaign name").fill("x");
  await page.getByTestId("save-campaign").click();
  await expect(page.getByTestId("campaign-form")).toContainText(
    "Name is too long.",
  );
  await expect(page.getByTestId("campaign-form")).not.toContainText("422");
});

test("manager edits a campaign (PATCH without keywords), pauses it, and manages keywords", async ({
  page,
}) => {
  const tenantId = await signIn(page, "manager");
  const many = await mockMany(page, tenantId, {
    ...campaignHandlers(),
    "PATCH facebook/campaigns/c1": () => ({ json: CAMPAIGN }),
    "POST facebook/campaigns/c1/keywords": () => ({
      json: { id: "k2", normalized_keyword: "price" },
    }),
    "DELETE facebook/campaigns/c1/keywords/k1": () => ({ json: {} }),
  });
  await page.goto(`/app/${tenantId}/facebook/campaigns`);
  // Pause from the status badge.
  await page.getByTestId("toggle-status-c1").click();
  await expect.poll(() => many.count("PATCH", "facebook/campaigns/c1")).toBe(1);
  expect(many.last("PATCH", "facebook/campaigns/c1")?.body).toEqual({
    status: "paused",
  });
  // Edit: keywords are managed one by one with their own routes.
  await page.getByTestId("edit-c1").click();
  const editor = page.getByTestId("keyword-editor");
  await editor.getByLabel("New keyword").fill("Price");
  await page.getByTestId("add-keyword").click();
  await expect(editor).toContainText("price");
  expect(many.last("POST", "facebook/campaigns/c1/keywords")?.body).toEqual({
    keyword: "Price",
  });
  await editor.getByRole("button", { name: "Remove keyword promo" }).click();
  await expect
    .poll(() => many.count("DELETE", "facebook/campaigns/c1/keywords/k1"))
    .toBe(1);
  await page.getByLabel("Campaign name").fill("Summer promo 2");
  await page.getByTestId("save-campaign").click();
  const patch = many.calls.filter(
    (c) => c.method === "PATCH" && c.path === "facebook/campaigns/c1",
  )[1];
  expect(patch.body).toMatchObject({ name: "Summer promo 2" });
  expect(patch.body).not.toHaveProperty("keywords");
  expect(patch.body).not.toHaveProperty("facebook_page_id");
});

test("manager cannot delete; admin deletes after confirming", async ({
  page,
}) => {
  const tenantId = await signIn(page, "manager");
  const many = await mockMany(page, tenantId, {
    ...campaignHandlers(),
    "DELETE facebook/campaigns/c1": () => ({ json: {} }),
  });
  await page.goto(`/app/${tenantId}/facebook/campaigns`);
  await expect(page.getByTestId("edit-c1")).toBeVisible();
  await expect(page.getByTestId("delete-c1")).toHaveCount(0);

  await page.unroute(`**/api/v1/tenants/${tenantId}/summary`);
  await mockRole(page, tenantId, "admin");
  await page.reload();
  await page.getByTestId("delete-c1").click();
  expect(many.count("DELETE", "facebook/campaigns/c1")).toBe(0);
  await page
    .locator("dialog[open]")
    .getByRole("button", { name: "Delete campaign" })
    .click();
  await expect
    .poll(() => many.count("DELETE", "facebook/campaigns/c1"))
    .toBe(1);
  await expect.poll(() => many.count("GET", "facebook/campaigns")).toBe(3);
});

// ------------------------------------------------------------ /accounts return

test("/accounts: one organization goes to its channels page and keeps the query", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  await mockMany(page, tenantId, channelHandlers());
  await page.goto("/accounts?connected=true&reconnected=true");
  await page.waitForURL(
    `**/app/${tenantId}/channels?connected=true&reconnected=true`,
  );
  await expect(page.getByTestId("channels-page")).toBeVisible();
});

test("/accounts: several organizations go to the organization list, query kept", async ({
  page,
}) => {
  const tenantId = await signIn(page, "admin");
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    const me = await response.json();
    const first = me.memberships[0];
    me.memberships = [
      first,
      { ...first, tenant_id: "00000000-0000-4000-8000-000000000002" },
    ];
    await route.fulfill({ response, json: me });
  });
  await page.goto("/accounts?error=oauth_failed");
  await page.waitForURL("**/app?error=oauth_failed");
  expect(tenantId).toBeTruthy();
});

test("/accounts: signed out goes to sign-in with a way back", async ({
  page,
}) => {
  await page.goto("/accounts?connected=true");
  await page.waitForURL(/\/login\?next=/);
  const next = new URL(page.url()).searchParams.get("next");
  expect(next).toBe("/accounts?connected=true");
});
