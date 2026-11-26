import { expect, test, type Page, type Route } from "@playwright/test";

import { registerAdmin, uniqueEmail } from "./e2e-helpers";
import { promoteToStaff } from "./staff-helpers";

/**
 * Phase 4D: the Instagram accounts and campaign pages for platform staff. The browser's
 * calls to /api/v1/many/... are answered by Playwright (no Many process here); the staff
 * guard and sign-in are the real API.
 */

type Call = { method: string; path: string; body: unknown };
type Reply = { status?: number; json?: unknown } | undefined;
type Handler = (call: Call) => Reply;

const ORG_NAME = "Ig Test Organization";

async function staffPage(page: Page) {
  const email = uniqueEmail("p4d-staff");
  const { tenantId } = await registerAdmin(page, "P4D", {
    email,
    organizationName: ORG_NAME,
  });
  promoteToStaff(email);
  return tenantId;
}

/** Answers every Many call through `handler` (undefined -> 404) and records the calls. */
async function mockMany(page: Page, handler: Handler) {
  const calls: Call[] = [];
  await page.route("**/api/v1/many/**", (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1/many/", "") + url.search;
    let body: unknown = null;
    try {
      body = request.postDataJSON();
    } catch {
      body = null;
    }
    const call = { method: request.method(), path, body };
    calls.push(call);
    const reply = handler(call);
    if (!reply) {
      return route.fulfill({
        status: 404,
        json: { error: { code: "NOT_FOUND", message: "no" } },
      });
    }
    return route.fulfill({
      status: reply.status ?? 200,
      json: reply.json ?? {},
    });
  });
  return calls;
}

const forbidden = {
  status: 403,
  json: { error: { code: "FORBIDDEN", message: "no" } },
};
const down = {
  status: 502,
  json: { error: { code: "MANY_UNAVAILABLE", message: "down" } },
};

function account(over: Record<string, unknown> = {}) {
  return {
    id: "acc-1",
    ig_user_id: "1784",
    username: "cafe_one",
    account_type: "BUSINESS",
    status: "connected",
    expires_at: null,
    ai_enabled: false,
    ai_daily_message_cap: 100,
    ai_messages_sent_today: 3,
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-20T10:00:00Z",
    ...over,
  };
}

function campaign(over: Record<string, unknown> = {}) {
  return {
    id: "cmp-1",
    workspace_id: "w1",
    instagram_account_id: "acc-1",
    name: "Summer sale",
    description: null,
    target_scope: "any_media",
    target_media_type: "unknown",
    match_type: "contains",
    message_template: "Hi {{username}}",
    link_url: null,
    cooldown_hours: 168,
    status: "paused",
    delivery_mode: "instant",
    total_triggers: 10,
    successful_sends: 8,
    failed_sends: 2,
    created_at: "2026-11-02T10:00:00Z",
    updated_at: "2026-11-02T10:00:00Z",
    keywords: [
      {
        id: "kw-1",
        campaign_id: "cmp-1",
        normalized_keyword: "link",
        created_at: "x",
      },
    ],
    ...over,
  };
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

/* ------------------------------------------------------------------ accounts */

const ACCOUNTS = "/platform/instagram/accounts";

test("accounts: the list shows each account with its state", async ({
  page,
}) => {
  await staffPage(page);
  await mockMany(page, ({ method, path }) =>
    method === "GET" && path === "staff/instagram/accounts"
      ? {
          json: [
            account(),
            account({
              id: "acc-2",
              username: "cafe_two",
              status: "disconnected",
            }),
          ],
        }
      : undefined,
  );
  await page.goto(ACCOUNTS);
  await expect(page.getByTestId("ig-account-acc-1")).toContainText("cafe_one");
  await expect(
    page.getByTestId("ig-account-acc-1").getByTestId("ig-account-state"),
  ).toHaveText("Connected");
  await expect(
    page.getByTestId("ig-account-acc-2").getByTestId("ig-account-state"),
  ).toHaveText("Disconnected");
});

test("accounts: empty state", async ({ page }) => {
  await staffPage(page);
  await mockMany(page, () => ({ json: [] }));
  await page.goto(ACCOUNTS);
  await expect(page.getByTestId("page-empty")).toBeVisible();
});

test("accounts: 403 is a forbidden state, 502 retries and recovers", async ({
  page,
}) => {
  await staffPage(page);
  await mockMany(page, () => forbidden);
  await page.goto(ACCOUNTS);
  const state = page.getByTestId("page-forbidden");
  await expect(state).toBeVisible();
  await expect(state).not.toContainText("403");

  await page.unrouteAll({ behavior: "wait" });
  let attempt = 0;
  await mockMany(page, () => (++attempt === 1 ? down : { json: [account()] }));
  await page.goto(ACCOUNTS);
  await expect(page.getByTestId("page-unavailable")).not.toContainText("down");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("ig-account-acc-1")).toBeVisible();
});

test("accounts: disconnect asks first, sends DELETE and refreshes", async ({
  page,
}) => {
  await staffPage(page);
  let disconnected = false;
  const calls = await mockMany(page, ({ method, path }) => {
    if (method === "DELETE" && path === "staff/instagram/accounts/acc-1") {
      disconnected = true;
      return { json: account({ status: "disconnected" }) };
    }
    if (method === "GET" && path === "staff/instagram/accounts") {
      return {
        json: [
          account({ status: disconnected ? "disconnected" : "connected" }),
        ],
      };
    }
    return undefined;
  });
  await page.goto(ACCOUNTS);
  await page.getByTestId("ig-disconnect-acc-1").click();
  expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  await page
    .getByRole("dialog", { name: /Disconnect cafe_one/ })
    .getByRole("button", { name: "Disconnect" })
    .click();
  await expect(
    page.getByTestId("ig-account-acc-1").getByTestId("ig-account-state"),
  ).toHaveText("Disconnected");
  expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
});

test("accounts: connect, reconnect and delete need an organization and use its scope", async ({
  page,
}) => {
  const tenantId = await staffPage(page);
  const calls = await mockMany(page, ({ method, path }) => {
    if (method === "GET" && path === "staff/instagram/accounts") {
      return { json: [account({ status: "disconnected" })] };
    }
    if (path === `orgs/${tenantId}/instagram/accounts/acc-1/hard`)
      return { status: 204 };
    return undefined;
  });
  await page.route("https://oauth.example.test/**", (route) =>
    route.fulfill({ contentType: "text/html", body: "<title>oauth</title>ok" }),
  );
  await page.goto(ACCOUNTS);
  await expect(page.getByTestId("ig-connect")).toBeDisabled();
  await expect(page.getByTestId("ig-reconnect-acc-1")).toBeDisabled();
  await expect(page.getByTestId("ig-delete-acc-1")).toBeDisabled();

  await page.getByTestId("ig-org-select").selectOption(tenantId);
  await expect(page.getByTestId("ig-connect")).toBeEnabled();

  // Permanent delete: workspace route, DELETE .../hard under the chosen organization.
  await page.getByTestId("ig-delete-acc-1").click();
  await page
    .getByRole("dialog", { name: "Delete account permanently?" })
    .getByRole("button", { name: "Delete permanently" })
    .click();
  await expect
    .poll(() =>
      calls.some(
        (c) =>
          c.method === "DELETE" &&
          c.path === `orgs/${tenantId}/instagram/accounts/acc-1/hard`,
      ),
    )
    .toBe(true);

  // Reconnect: POST .../reconnect under the organization, then the browser follows the https address.
  await page.unroute("**/api/v1/many/**");
  const second = await mockMany(page, ({ method, path }) => {
    if (method === "GET" && path === "staff/instagram/accounts") {
      return { json: [account({ status: "disconnected" })] };
    }
    if (
      method === "POST" &&
      path === `orgs/${tenantId}/instagram/accounts/acc-1/reconnect`
    ) {
      return { json: { oauth_url: "https://oauth.example.test/dialog" } };
    }
    return undefined;
  });
  await page.reload();
  await page.getByTestId("ig-org-select").selectOption(tenantId);
  await page.getByTestId("ig-reconnect-acc-1").click();
  await expect(page).toHaveURL(/oauth\.example\.test\/dialog/);
  expect(
    second.some((c) => c.method === "POST" && c.path.endsWith("/reconnect")),
  ).toBe(true);
});

test("accounts: connect calls the organization route and refuses a non-https address", async ({
  page,
}) => {
  const tenantId = await staffPage(page);
  const calls = await mockMany(page, ({ method, path }) => {
    if (method === "GET" && path === "staff/instagram/accounts")
      return { json: [account()] };
    if (method === "GET" && path === `orgs/${tenantId}/meta/connect/start`) {
      return { json: { oauth_url: "http://insecure.example.test/" } };
    }
    return undefined;
  });
  await page.goto(ACCOUNTS);
  await page.getByTestId("ig-org-select").selectOption(tenantId);
  await page.getByTestId("ig-connect").click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Could not start" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/platform\/instagram\/accounts/);
  expect(
    calls.some((c) => c.path === `orgs/${tenantId}/meta/connect/start`),
  ).toBe(true);
});

test("accounts: health, AI settings and SaaS delegation send the right calls", async ({
  page,
}) => {
  await staffPage(page);
  const delegation = {
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
  const calls = await mockMany(page, ({ method, path, body }) => {
    if (path === "staff/instagram/accounts") return { json: [account()] };
    if (path === "staff/instagram/accounts/acc-1/health") {
      return {
        json: { account_id: "acc-1", has_token: true, status: "healthy" },
      };
    }
    if (
      path === "staff/instagram/accounts/acc-1/ai-settings" &&
      method === "PATCH"
    ) {
      return { json: account({ ai_enabled: true }) };
    }
    if (path === "staff/instagram/accounts/acc-1/saas-delegation") {
      if (method === "PATCH") {
        return {
          json: {
            ...delegation,
            saas_delegation_enabled: true,
            saas_connection_id: (body as { saas_connection_id: string })
              .saas_connection_id,
            secret_set: true,
          },
        };
      }
      return { json: delegation };
    }
    return undefined;
  });
  await page.goto(ACCOUNTS);
  await page.getByTestId("ig-toggle-acc-1").click();

  await page.getByTestId("ig-health-check").click();
  await expect(page.getByTestId("ig-health-result")).toContainText(
    "A token is stored",
  );

  await page.getByTestId("ig-ai-enabled").click();
  await page.getByLabel("Daily message cap").fill("250");
  await page.getByLabel("Business profile").fill("Open 9 to 5");
  await page.getByTestId("ig-ai-save").click();
  await expect(
    page.getByTestId("ig-ai-settings").getByText("AI settings saved."),
  ).toBeVisible();
  const ai = calls.find(
    (c) => c.method === "PATCH" && c.path.endsWith("/ai-settings"),
  );
  expect(ai?.body).toMatchObject({
    ai_enabled: true,
    ai_daily_message_cap: 250,
    ai_business_profile: "Open 9 to 5",
    business_vertical: "general",
  });

  await page.getByLabel("Connection ID").fill("conn-9");
  await page.getByLabel("SaaS base URL").fill("https://saas.example.test");
  await page.getByLabel("Signing secret").fill("s".repeat(40));
  await page.getByTestId("ig-delegation-enable").click();
  await expect(page.getByTestId("ig-delegation-state")).toHaveText("Delegated");
  const patch = calls.find(
    (c) => c.method === "PATCH" && c.path.endsWith("/saas-delegation"),
  );
  expect(patch?.body).toEqual({
    saas_connection_id: "conn-9",
    saas_base_url: "https://saas.example.test",
    secret: "s".repeat(40),
    saas_delegation_enabled: true,
  });
  // Delegated accounts never get Many's take over or resume controls.
  await expect(
    page.getByRole("button", { name: /take over|resume/i }),
  ).toHaveCount(0);
});

/* ----------------------------------------------------------------- campaigns */

const CAMPAIGNS = "/platform/instagram/campaigns";

function listHandler(state: { rows: ReturnType<typeof campaign>[] }): Handler {
  return ({ method, path }) => {
    if (method === "GET" && path === "staff/campaigns")
      return { json: state.rows };
    if (method === "GET" && path === "staff/instagram/accounts")
      return { json: [account()] };
    return undefined;
  };
}

test("campaigns: the list shows data and filters by status", async ({
  page,
}) => {
  await staffPage(page);
  await mockMany(
    page,
    listHandler({
      rows: [
        campaign(),
        campaign({ id: "cmp-2", name: "Live one", status: "active" }),
        campaign({ id: "cmp-3", name: "Old one", status: "archived" }),
      ],
    }),
  );
  await page.goto(CAMPAIGNS);
  await expect(page.getByRole("link", { name: "Edit" })).toHaveCount(3);
  await expect(page.getByTestId("ig-filter-active")).toContainText("(1)");
  await page.getByTestId("ig-filter-active").click();
  await expect(page.getByText("Live one")).toBeVisible();
  await expect(page.getByText("Summer sale")).toHaveCount(0);
});

test("campaigns: empty, 403 and 502 states", async ({ page }) => {
  await staffPage(page);
  await mockMany(page, listHandler({ rows: [] }));
  await page.goto(CAMPAIGNS);
  await expect(page.getByTestId("page-empty")).toBeVisible();

  await page.unrouteAll({ behavior: "wait" });
  await mockMany(page, () => forbidden);
  await page.goto(CAMPAIGNS);
  await expect(page.getByTestId("page-forbidden")).toBeVisible();

  await page.unrouteAll({ behavior: "wait" });
  let attempt = 0;
  const state = { rows: [campaign()] };
  const ok = listHandler(state);
  await mockMany(page, (call) => (++attempt <= 2 ? down : ok(call)));
  await page.goto(CAMPAIGNS);
  await expect(page.getByTestId("page-unavailable")).toBeVisible();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Summer sale")).toBeVisible();
});

test("campaigns: activate, pause, archive and unarchive POST the action and refresh", async ({
  page,
}) => {
  await staffPage(page);
  const state = { rows: [campaign()] };
  const base = listHandler(state);
  const calls = await mockMany(page, (call) => {
    const match = call.path.match(
      /^staff\/campaigns\/cmp-1\/(activate|pause|archive|unarchive)$/,
    );
    if (call.method === "POST" && match) {
      state.rows = [
        campaign({
          status: {
            activate: "active",
            pause: "paused",
            archive: "archived",
            unarchive: "paused",
          }[match[1]],
        }),
      ];
      return { json: state.rows[0] };
    }
    return base(call);
  });
  await page.goto(CAMPAIGNS);
  await page.getByTestId("ig-activate-cmp-1").click();
  await expect(page.getByTestId("ig-pause-cmp-1")).toBeVisible();
  await page.getByTestId("ig-pause-cmp-1").click();
  await expect(page.getByTestId("ig-activate-cmp-1")).toBeVisible();
  await page.getByTestId("ig-archive-cmp-1").click();
  await expect(page.getByTestId("ig-unarchive-cmp-1")).toBeVisible();
  await page.getByTestId("ig-unarchive-cmp-1").click();
  await expect(page.getByTestId("ig-activate-cmp-1")).toBeVisible();
  expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual([
    "staff/campaigns/cmp-1/activate",
    "staff/campaigns/cmp-1/pause",
    "staff/campaigns/cmp-1/archive",
    "staff/campaigns/cmp-1/unarchive",
  ]);
});

test("campaigns: a failed action shows its message and keeps the row", async ({
  page,
}) => {
  await staffPage(page);
  const base = listHandler({ rows: [campaign()] });
  await mockMany(page, (call) =>
    call.method === "POST"
      ? { status: 409, json: { detail: "Reconnect the account first." } }
      : base(call),
  );
  await page.goto(CAMPAIGNS);
  await page.getByTestId("ig-activate-cmp-1").click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Reconnect the account first." }),
  ).toBeVisible();
  await expect(page.getByText("Summer sale")).toBeVisible();
});

test("campaigns: permanent delete needs an archived campaign and the typed phrase", async ({
  page,
}) => {
  await staffPage(page);
  const state = {
    rows: [
      campaign({ status: "archived" }),
      campaign({ id: "cmp-2", name: "Active", status: "active" }),
    ],
  };
  const base = listHandler(state);
  const calls = await mockMany(page, (call) => {
    if (call.method === "DELETE" && call.path === "staff/campaigns/cmp-1") {
      state.rows = state.rows.filter((r) => r.id !== "cmp-1");
      return { status: 204 };
    }
    return base(call);
  });
  await page.goto(CAMPAIGNS);
  await expect(page.getByTestId("ig-select-cmp-2")).toBeDisabled();
  await expect(page.getByTestId("ig-delete-selected")).toBeDisabled();
  await page.getByTestId("ig-select-cmp-1").check();
  await page.getByTestId("ig-delete-selected").click();
  const confirm = page.getByTestId("ig-delete-confirm-button");
  await expect(confirm).toBeDisabled();
  await page.getByTestId("ig-delete-confirm").fill("delete Summer sale");
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(page.getByText("Campaign deleted permanently.")).toBeVisible();
  expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(
    ["staff/campaigns/cmp-1"],
  );
  await expect(page.getByTestId("ig-select-cmp-1")).toHaveCount(0);
});

test("campaigns: a new campaign is created as a draft, then activated from the form", async ({
  page,
}) => {
  await staffPage(page);
  const created = campaign({ id: "cmp-9", name: "Launch", keywords: [] });
  const calls = await mockMany(page, ({ method, path }) => {
    if (method === "GET" && path === "staff/instagram/accounts")
      return { json: [account()] };
    if (method === "POST" && path === "staff/campaigns")
      return { status: 201, json: created };
    if (method === "POST" && path === "staff/campaigns/cmp-9/activate") {
      return { json: { ...created, status: "active" } };
    }
    if (method === "GET" && path === "staff/campaigns")
      return { json: [{ ...created, status: "active" }] };
    return undefined;
  });
  await page.goto(`${CAMPAIGNS}/new`);
  await page.getByTestId("ig-name").fill("Launch");
  await expect(page.getByTestId("ig-account")).toHaveValue("acc-1");
  await page.getByTestId("ig-keyword-input").fill("price");
  await page.getByTestId("ig-keyword-add").click();
  await page.getByTestId("ig-activate").click();
  await expect(page).toHaveURL(/\/platform\/instagram\/campaigns$/);
  const post = calls.find(
    (c) => c.method === "POST" && c.path === "staff/campaigns",
  );
  expect(post?.body).toMatchObject({
    instagram_account_id: "acc-1",
    name: "Launch",
    status: "draft",
    keywords: ["price"],
    target_scope: "any_media",
    delivery_mode: "instant",
    cooldown_hours: 168,
  });
  expect(calls.some((c) => c.path === "staff/campaigns/cmp-9/activate")).toBe(
    true,
  );
});

test("campaigns: a specific post can be picked from the account media", async ({
  page,
}) => {
  await staffPage(page);
  const calls = await mockMany(page, ({ method, path }) => {
    if (path === "staff/instagram/accounts") return { json: [account()] };
    if (path.startsWith("staff/instagram/accounts/acc-1/media")) {
      return {
        json: {
          account_id: "acc-1",
          media: [
            {
              media_id: "m-1",
              caption: "c",
              label: "Reel one",
              media_type: "VIDEO",
              permalink: "https://www.instagram.com/reel/SC1/",
            },
            {
              media_id: "m-2",
              caption: "c",
              label: "Photo",
              media_type: "IMAGE",
              permalink: "https://www.instagram.com/p/SC2/",
            },
          ],
          next_cursor: null,
        },
      };
    }
    if (method === "POST" && path === "staff/campaigns")
      return { status: 201, json: campaign({ id: "cmp-5", keywords: [] }) };
    return undefined;
  });
  await page.goto(`${CAMPAIGNS}/new`);
  await page.getByTestId("ig-name").fill("Reel promo");
  await page.getByTestId("ig-scope-specific").check();
  await page.getByTestId("ig-media-m-1").click();
  await expect(page.getByTestId("ig-media-chosen")).toContainText("m-1");
  expect(
    calls.some(
      (c) => c.path === "staff/instagram/accounts/acc-1/media?limit=24",
    ),
  ).toBe(true);
  await page.getByTestId("ig-save-draft").click();
  await expect
    .poll(
      () =>
        calls.find((c) => c.method === "POST" && c.path === "staff/campaigns")
          ?.body,
    )
    .toMatchObject({
      target_scope: "specific_media",
      target_media_id: "m-1",
      target_media_type: "reel",
      target_media_shortcode: "SC1",
      target_media_label: "Reel one",
    });
});

test("campaigns: editing PATCHes the fields, syncs keywords and can run a test", async ({
  page,
}) => {
  await staffPage(page);
  const existing = campaign({
    keywords: [
      {
        id: "kw-1",
        campaign_id: "cmp-1",
        normalized_keyword: "link",
        created_at: "x",
      },
      {
        id: "kw-2",
        campaign_id: "cmp-1",
        normalized_keyword: "old",
        created_at: "x",
      },
    ],
  });
  const calls = await mockMany(page, ({ method, path }) => {
    if (path === "staff/instagram/accounts") return { json: [account()] };
    if (method === "GET" && path === "staff/campaigns/cmp-1")
      return { json: existing };
    if (method === "PATCH" && path === "staff/campaigns/cmp-1")
      return { json: existing };
    if (method === "POST" && path.startsWith("staff/campaigns/cmp-1/keywords"))
      return { json: {} };
    if (method === "DELETE" && path === "staff/campaigns/cmp-1/keywords/kw-2")
      return { status: 204 };
    if (method === "POST" && path === "staff/campaigns/cmp-1/simulate") {
      return {
        json: {
          matched: true,
          matched_keyword: "link",
          rendered_message: "Hi sam",
        },
      };
    }
    return undefined;
  });
  await page.goto(`${CAMPAIGNS}/cmp-1`);
  await expect(page.getByTestId("ig-name")).toHaveValue("Summer sale");

  await page.getByTestId("ig-test-open").click();
  await page.getByTestId("ig-test-comment").fill("send me the link");
  await page.getByTestId("ig-test-run").click();
  await expect(page.getByTestId("ig-test-result")).toContainText(
    "Matched: Yes",
  );
  await expect(page.getByTestId("ig-test-result")).toContainText("Hi sam");
  expect(
    calls.find((c) => c.path === "staff/campaigns/cmp-1/simulate")?.body,
  ).toEqual({
    comment_text: "send me the link",
    username: "",
  });
  await page.getByRole("button", { name: "Close", exact: true }).click();

  await page.getByTestId("ig-name").fill("Summer sale 2");
  await page.getByRole("button", { name: "Remove keyword old" }).click();
  await page.getByTestId("ig-keyword-input").fill("new word");
  await page.getByTestId("ig-keyword-add").click();
  await page.getByTestId("ig-save-draft").click();

  await expect.poll(() => calls.some((c) => c.method === "DELETE")).toBe(true);
  const patch = calls.find((c) => c.method === "PATCH");
  expect(patch?.path).toBe("staff/campaigns/cmp-1");
  expect(patch?.body).toMatchObject({
    name: "Summer sale 2",
    cooldown_hours: 168,
  });
  expect(patch?.body).not.toHaveProperty("status");
  expect(
    calls.some(
      (c) =>
        c.method === "POST" &&
        c.path === "staff/campaigns/cmp-1/keywords?keyword=new%20word",
    ),
  ).toBe(true);
  expect(
    calls.some(
      (c) =>
        c.method === "DELETE" &&
        c.path === "staff/campaigns/cmp-1/keywords/kw-2",
    ),
  ).toBe(true);
});

test("campaigns: a save error stays on the form with a plain message", async ({
  page,
}) => {
  await staffPage(page);
  await mockMany(page, ({ method, path }) => {
    if (path === "staff/instagram/accounts") return { json: [account()] };
    if (method === "POST" && path === "staff/campaigns") {
      return { status: 422, json: { detail: [{ msg: "name too long" }] } };
    }
    return undefined;
  });
  await page.goto(`${CAMPAIGNS}/new`);
  await page.getByTestId("ig-name").fill("x");
  await page.getByTestId("ig-save-draft").click();
  await expect(page.getByTestId("ig-form-error")).toContainText(
    "name too long",
  );
  await expect(page).toHaveURL(/\/campaigns\/new$/);
});

test("campaigns: an unknown campaign shows the not-available state", async ({
  page,
}) => {
  await staffPage(page);
  await mockMany(page, () => undefined);
  await page.goto(`${CAMPAIGNS}/missing`);
  await expect(page.getByTestId("page-not_available")).toBeVisible();
});

/* --------------------------------------------------------------------- stats */

function stats(over: Record<string, unknown> = {}) {
  return {
    campaign_id: "cmp-1",
    name: "Summer sale",
    status: "active",
    created_at: "2026-11-02T10:00:00Z",
    created_by: "ops@example.test",
    account_username: "cafe_one",
    target_scope: "any_media",
    target_media_type: "unknown",
    keywords: ["link"],
    match_type: "contains",
    cooldown_hours: 168,
    delivery_mode: "instant",
    message_template: "Hi {{username}}",
    new_leads: 4,
    total_triggers: 10,
    successful_sends: 7,
    failed_sends: 2,
    expired: 0,
    cooldowns: 1,
    recent_messages: [
      {
        id: "msg-1",
        status: "failed",
        username: "sam",
        error_message: "Window closed",
        created_at: "2026-11-03T10:00:00Z",
      },
      {
        id: "msg-2",
        status: "sent",
        username: "lee",
        created_at: "2026-11-03T11:00:00Z",
      },
      {
        id: "msg-3",
        status: "failed",
        username: "kim",
        created_at: "2026-11-03T12:00:00Z",
      },
    ],
    recent_logs: [
      {
        id: "log-1",
        event_type: "message_sent",
        message: "Sent",
        metadata: {},
        created_at: "2026-11-03T10:00:00Z",
      },
    ],
    ...over,
  };
}

test("stats: shows the numbers and retries every failed message", async ({
  page,
}) => {
  await staffPage(page);
  const calls = await mockMany(page, ({ method, path }) => {
    if (method === "GET" && path === "staff/campaigns/cmp-1/stats")
      return { json: stats() };
    if (method === "POST" && /^staff\/messages\/msg-\d\/retry$/.test(path))
      return { json: {} };
    return undefined;
  });
  await page.goto(`${CAMPAIGNS}/cmp-1/stats`);
  await expect(page.getByTestId("ig-kpis")).toContainText("Total triggers");
  await expect(page.getByTestId("ig-kpis")).toContainText("10");
  await expect(page.getByTestId("ig-messages")).toContainText("Window closed");
  await page.getByTestId("ig-retry-failed").click();
  await expect(
    page.getByText("Failed messages queued for retry."),
  ).toBeVisible();
  expect(
    calls
      .filter((c) => c.method === "POST")
      .map((c) => c.path)
      .sort(),
  ).toEqual(["staff/messages/msg-1/retry", "staff/messages/msg-3/retry"]);
});

test("stats: 403 and 502 are page states", async ({ page }) => {
  await staffPage(page);
  await mockMany(page, () => forbidden);
  await page.goto(`${CAMPAIGNS}/cmp-1/stats`);
  await expect(page.getByTestId("page-forbidden")).toBeVisible();

  await page.unrouteAll({ behavior: "wait" });
  let attempt = 0;
  await mockMany(page, () => (++attempt === 1 ? down : { json: stats() }));
  await page.goto(`${CAMPAIGNS}/cmp-1/stats`);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("ig-kpis")).toBeVisible();
});

test("a client cannot open the Instagram staff pages, and no Many call is made", async ({
  page,
}) => {
  await registerAdmin(page, "P4D-client");
  let calls = 0;
  await page.route("**/api/v1/many/**", (route) => {
    calls += 1;
    return route.fulfill({ status: 200, json: [] });
  });
  for (const path of [
    ACCOUNTS,
    CAMPAIGNS,
    `${CAMPAIGNS}/new`,
    `${CAMPAIGNS}/cmp-1/stats`,
  ]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login/);
  }
  expect(calls).toBe(0);
});
