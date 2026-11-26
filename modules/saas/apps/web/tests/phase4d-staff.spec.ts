import { expect, test, type Page, type Route } from "@playwright/test";

import { registerAdmin, uniqueEmail } from "./e2e-helpers";
import { promoteToStaff } from "./staff-helpers";

/**
 * Phase 4D: the staff Many pages (leads, messages, logs, Instagram conversations) through the
 * SaaS proxy. The browser's calls to /api/v1/many/staff/... are answered by Playwright (no Many
 * process here); the staff guard and the sign-in are the real API.
 */

type Handler = (
  path: string,
  method: string,
  url: URL,
  body: unknown,
) => { status?: number; json: unknown } | undefined;

async function signedInStaff(page: Page) {
  const email = uniqueEmail("p4d-staff");
  await registerAdmin(page, "P4D", { email });
  promoteToStaff(email);
}

/** Answers every Many staff call with `handler`; unknown paths get an empty list. */
async function mockMany(page: Page, handler: Handler) {
  const calls: {
    method: string;
    path: string;
    query: string;
    body: unknown;
  }[] = [];
  await page.route("**/api/v1/many/staff/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^.*\/api\/v1\/many\/staff\//, "");
    let body: unknown = null;
    try {
      body = request.postDataJSON();
    } catch {
      body = null;
    }
    calls.push({
      method: request.method(),
      path,
      query: url.search,
      body,
    });
    const answer = handler(path, request.method(), url, body);
    if (answer) {
      return route.fulfill({ status: answer.status ?? 200, json: answer.json });
    }
    return route.fulfill({ json: [] });
  });
  return calls;
}

const FORBIDDEN = {
  status: 403,
  json: { error: { code: "FORBIDDEN", message: "no" } },
};
const DOWN = {
  status: 502,
  json: { error: { code: "MANY_UNAVAILABLE", message: "down" } },
};

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

const LEADS = [
  {
    id: "l1",
    username: "maria",
    ig_user_id: "1001",
    lead_source: "campaign",
    platform: "instagram",
    source_campaign: "Spring sale",
    keyword: "PRICE",
    instagram_account_username: "shop_ig",
    captured_at: "2026-05-01T10:00:00Z",
  },
  {
    id: "l2",
    username: "omar",
    ig_user_id: "1002",
    lead_source: "cold_dm",
    platform: "whatsapp",
    whatsapp_account_username: "+971500000000",
    captured_at: "2026-05-02T10:00:00Z",
  },
];

// ---------------------------------------------------------------- leads

test("leads: renders rows, filters are sent as the old page sent them", async ({
  page,
}) => {
  await signedInStaff(page);
  const calls = await mockMany(page, (path) => {
    if (path === "leads") return { json: LEADS };
    if (path === "campaigns")
      return { json: [{ id: "c1", name: "Spring sale", status: "active" }] };
    if (path === "instagram/accounts")
      return { json: [{ id: "a1", username: "shop_ig", ig_user_id: "9" }] };
    return undefined;
  });
  await page.goto("/platform/leads");
  const table = page.getByTestId("staff-leads");
  await expect(table).toContainText("maria");
  await expect(table).toContainText("Spring sale");
  await expect(table).toContainText("PRICE");
  await expect(table).toContainText("+971500000000");

  // Platform is filtered on the loaded rows: no new request, the WhatsApp row stays.
  const before = calls.filter((c) => c.path === "leads").length;
  await page.getByLabel("Platform").selectOption("whatsapp");
  await expect(table).not.toContainText("maria");
  await expect(table).toContainText("omar");
  expect(calls.filter((c) => c.path === "leads").length).toBe(before);

  // Campaign and account go to the server.
  await page.getByLabel("Campaign").selectOption("c1");
  await expect
    .poll(() => calls.some((c) => c.query.includes("campaign_id=c1")))
    .toBe(true);
  await page.getByLabel("Instagram account").selectOption("a1");
  await expect
    .poll(() =>
      calls.some(
        (c) =>
          c.query.includes("campaign_id=c1") &&
          c.query.includes("instagram_account_id=a1"),
      ),
    )
    .toBe(true);
  await page.getByLabel("Search username").fill("mar");
  await expect
    .poll(() => calls.some((c) => c.query.includes("search=mar")))
    .toBe(true);
});

test("leads: long lists are paged", async ({ page }) => {
  await signedInStaff(page);
  const many = Array.from({ length: 120 }, (_, i) => ({
    id: `l${i}`,
    username: `user${i}`,
    ig_user_id: String(i),
    platform: "instagram",
  }));
  await mockMany(page, (path) =>
    path === "leads" ? { json: many } : undefined,
  );
  await page.goto("/platform/leads");
  await expect(page.getByTestId("pager-status")).toContainText(
    "1 to 50 of 120",
  );
  await page.getByTestId("pager-next").click();
  await expect(page.getByTestId("pager-status")).toContainText(
    "51 to 100 of 120",
  );
  await expect(page.getByTestId("staff-leads")).toContainText("user50");
});

test("leads: empty state keeps the filters", async ({ page }) => {
  await signedInStaff(page);
  await mockMany(page, () => ({ json: [] }));
  await page.goto("/platform/leads");
  await expect(page.getByTestId("page-empty")).toContainText("No leads found");
  await expect(page.getByLabel("Search username")).toBeVisible();
});

for (const [name, answer, testId] of [
  ["a 403 shows the forbidden state", FORBIDDEN, "page-forbidden"],
  ["a 502 shows the unavailable state", DOWN, "page-unavailable"],
] as const) {
  test(`leads: ${name}`, async ({ page }) => {
    await signedInStaff(page);
    await mockMany(page, (path) => (path === "leads" ? answer : undefined));
    await page.goto("/platform/leads");
    const state = page.getByTestId(testId);
    await expect(state).toBeVisible();
    await expect(state).not.toContainText("403");
    await expect(state).not.toContainText("502");
    await expect(page.getByTestId("staff-leads")).toHaveCount(0);
  });
}

test("leads: retry after a 502 recovers", async ({ page }) => {
  await signedInStaff(page);
  let attempt = 0;
  await mockMany(page, (path) => {
    if (path !== "leads") return undefined;
    attempt += 1;
    return attempt === 1 ? DOWN : { json: LEADS };
  });
  await page.goto("/platform/leads");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("staff-leads")).toContainText("maria");
});

// ------------------------------------------------------------- messages

const MESSAGES = [
  {
    id: "m1",
    campaign_id: "c1",
    lead_id: "l1",
    status: "failed",
    message_type: "final_delivery",
    error_message: "Window closed",
    trigger_keyword: "PRICE",
    retryable: true,
    retry_count: 2,
  },
  {
    id: "m2",
    campaign_id: "None",
    lead_id: "l2",
    status: "sent",
    message_type: "follow_prompt",
    retryable: false,
    retry_count: 0,
    created_at: "2026-05-02T10:00:00Z",
  },
  {
    id: "m3",
    campaign_id: "c1",
    lead_id: "l1",
    status: "failed",
    retryable: false,
    retry_count: 1,
  },
];

function messagesHandler(onRetry?: () => void): Handler {
  return (path, method) => {
    if (path === "messages") return { json: MESSAGES };
    if (path === "campaigns")
      return { json: [{ id: "c1", name: "Spring sale" }] };
    if (path === "leads") return { json: LEADS };
    if (path === "messages/m1/retry" && method === "POST") {
      onRetry?.();
      return { json: { ok: true } };
    }
    return undefined;
  };
}

test("messages: renders names, cold DM and only retryable failures get Retry", async ({
  page,
}) => {
  await signedInStaff(page);
  await mockMany(page, messagesHandler());
  await page.goto("/platform/messages");
  const table = page.getByTestId("staff-messages");
  await expect(table).toContainText("Spring sale");
  await expect(table).toContainText("maria");
  await expect(table).toContainText("Cold DM");
  await expect(table).toContainText("Window closed");
  await expect(table).toContainText("2 retries");
  await expect(page.getByTestId("retry-m1")).toBeVisible();
  await expect(page.getByTestId("retry-m2")).toHaveCount(0);
  await expect(page.getByTestId("retry-m3")).toHaveCount(0);
});

test("messages: Retry posts to the message and refreshes the list", async ({
  page,
}) => {
  await signedInStaff(page);
  let retries = 0;
  const calls = await mockMany(
    page,
    messagesHandler(() => (retries += 1)),
  );
  await page.goto("/platform/messages");
  const listCalls = () => calls.filter((c) => c.path === "messages").length;
  await expect(page.getByTestId("retry-m1")).toBeVisible();
  const before = listCalls();
  await page.getByTestId("retry-m1").click();
  await expect(page.getByText("Message retry queued.")).toBeVisible();
  const post = calls.find((c) => c.path === "messages/m1/retry");
  expect(post?.method).toBe("POST");
  expect(retries).toBe(1);
  await expect.poll(listCalls).toBeGreaterThan(before);
});

test("messages: a failed retry shows the plain message, not a status", async ({
  page,
}) => {
  await signedInStaff(page);
  await mockMany(page, (path, method) => {
    if (path === "messages/m1/retry" && method === "POST")
      return { status: 409, json: { detail: "Already retried." } };
    return messagesHandler()(path, method, new URL("http://x"), null);
  });
  await page.goto("/platform/messages");
  await page.getByTestId("retry-m1").click();
  await expect(page.getByRole("alert")).toContainText("Already retried.");
  await expect(page.getByRole("alert")).not.toContainText("409");
});

test("messages: empty, 403 and 502", async ({ page }) => {
  await signedInStaff(page);
  let mode: "empty" | "forbidden" | "down" = "empty";
  await mockMany(page, (path) => {
    if (path !== "messages") return undefined;
    if (mode === "forbidden") return FORBIDDEN;
    if (mode === "down") return DOWN;
    return { json: [] };
  });
  await page.goto("/platform/messages");
  await expect(page.getByTestId("page-empty")).toContainText("No messages yet");
  mode = "forbidden";
  await page.reload();
  await expect(page.getByTestId("page-forbidden")).toBeVisible();
  mode = "down";
  await page.reload();
  await expect(page.getByTestId("page-unavailable")).toBeVisible();
  mode = "empty";
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("page-empty")).toBeVisible();
});

// ----------------------------------------------------------------- logs

const LOGS = [
  {
    id: "g1",
    level: "info",
    event_type: "webhook_received",
    message: "Comment arrived",
    metadata: { comment_id: "cm1", sender: "maria" },
    created_at: "2026-05-01T10:00:00Z",
  },
  {
    id: "g2",
    level: "info",
    event_type: "campaign_matched",
    message: "Matched Spring",
    metadata: { comment_id: "cm1" },
    created_at: "2026-05-01T10:00:01Z",
  },
  {
    id: "g3",
    level: "error",
    event_type: "login_failed",
    message: "Bad password",
    metadata: {},
    actor_email: "who@example.com",
    created_at: "2026-05-01T09:00:00Z",
  },
];

test("logs: groups a message flow, expands it and shows metadata", async ({
  page,
}) => {
  await signedInStaff(page);
  await mockMany(page, (path) => {
    if (path === "logs") return { json: LOGS };
    if (path === "campaigns")
      return { json: [{ id: "c1", name: "Spring", status: "active" }] };
    return undefined;
  });
  await page.goto("/platform/logs");
  await expect(page.getByTestId("log-group")).toHaveCount(1);
  await expect(page.getByTestId("log-single")).toHaveCount(1);
  const group = page.getByTestId("log-group");
  await expect(group).toContainText("Message flow");
  await expect(group).toContainText("2 events");
  await expect(group).not.toContainText("Matched Spring");
  await group.getByRole("button", { name: "Expand grouped events" }).click();
  await expect(group).toContainText("Matched Spring");
  await expect(page.getByTestId("log-single")).toContainText("Bad password");
  await expect(page.getByTestId("log-single")).toContainText("who@example.com");

  await expect(page.getByTestId("log-metadata")).toHaveCount(0);
  await group.getByTestId("log-metadata-toggle").click();
  await expect(page.getByTestId("log-metadata")).toContainText("Comment Id");
  await expect(page.getByTestId("log-metadata")).toContainText("cm1");
});

test("logs: filters go to the server with the old parameter names", async ({
  page,
}) => {
  await signedInStaff(page);
  const calls = await mockMany(page, (path) => {
    if (path === "logs") return { json: LOGS };
    if (path === "campaigns")
      return { json: [{ id: "c1", name: "Spring", status: "active" }] };
    return undefined;
  });
  await page.goto("/platform/logs");
  await expect(page.getByTestId("staff-logs")).toBeVisible();
  expect(calls.find((c) => c.path === "logs")?.query).toBe("?limit=100");
  await page.getByLabel("Level").selectOption("error");
  await page.getByLabel("Campaign").selectOption("c1");
  await page.getByLabel("Event type").selectOption({ label: "Login failed" });
  await page.getByLabel("Limit").fill("25");
  await expect
    .poll(() =>
      calls.some(
        (c) =>
          c.path === "logs" &&
          c.query.includes("level=error") &&
          c.query.includes("campaign_id=c1") &&
          c.query.includes("event_type=login_failed") &&
          c.query.includes("limit=25"),
      ),
    )
    .toBe(true);
});

test("logs: empty, 403 and 502", async ({ page }) => {
  await signedInStaff(page);
  let mode: "empty" | "forbidden" | "down" = "empty";
  await mockMany(page, (path) => {
    if (path !== "logs") return undefined;
    if (mode === "forbidden") return FORBIDDEN;
    if (mode === "down") return DOWN;
    return { json: [] };
  });
  await page.goto("/platform/logs");
  await expect(page.getByTestId("page-empty")).toContainText("No logs found");
  await expect(page.getByLabel("Level")).toBeVisible();
  mode = "forbidden";
  await page.reload();
  await expect(page.getByTestId("page-forbidden")).toBeVisible();
  mode = "down";
  await page.reload();
  await expect(page.getByTestId("page-unavailable")).toBeVisible();
  mode = "empty";
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("page-empty")).toBeVisible();
});

// -------------------------------------------------------- conversations

const CONVERSATIONS = [
  {
    id: "v1",
    lead_id: "l1",
    lead_username: "maria",
    platform: "instagram",
    status: "bot_active",
    turn_count: 3,
    campaign_name: "Spring sale",
    managed_by_saas: false,
  },
  {
    id: "v2",
    lead_id: "l2",
    lead_username: "omar",
    platform: "instagram",
    status: "handed_off",
    turn_count: 5,
    managed_by_saas: false,
  },
  {
    id: "v3",
    lead_id: "l3",
    lead_username: "lina",
    platform: "instagram",
    status: "bot_active",
    turn_count: 1,
    managed_by_saas: true,
  },
  {
    id: "v4",
    lead_id: "l4",
    lead_username: "sam",
    platform: "instagram",
    status: "bot_active",
    turn_count: 1,
    managed_by_saas: true,
    tenant_id: "tenant-42",
  },
];

function conversationsHandler(onAction?: (path: string) => void): Handler {
  return (path, method) => {
    if (path === "conversations") return { json: CONVERSATIONS };
    const detail = /^conversations\/(v\d)$/.exec(path);
    if (detail && method === "GET") {
      const row = CONVERSATIONS.find((c) => c.id === detail[1]);
      return {
        json: {
          ...row,
          messages: [
            {
              id: "x1",
              direction: "inbound",
              content: "Hi there",
              status: "sent",
            },
            {
              id: "x2",
              direction: "outbound",
              content: "Hello!",
              status: "failed",
            },
          ],
        },
      };
    }
    if (
      /^conversations\/v\d\/(take-over|resume-bot)$/.test(path) &&
      method === "POST"
    ) {
      onAction?.(path);
      return { json: { ok: true } };
    }
    return undefined;
  };
}

test("conversations: delegated rows show the shared inbox, never take over or resume", async ({
  page,
}) => {
  await signedInStaff(page);
  const calls = await mockMany(page, conversationsHandler());
  await page.goto("/platform/instagram/conversations");
  const table = page.getByTestId("staff-conversations");
  await expect(table).toContainText("maria");

  // No tenant id: a badge only.
  await expect(page.getByTestId("handled-in-shared-inbox")).toHaveCount(1);
  // A tenant id: a link to that organization's inbox.
  const link = page.getByTestId("open-shared-inbox");
  await expect(link).toHaveCount(1);
  await expect(link).toHaveText("Open in the shared inbox");
  await expect(link).toHaveAttribute("href", "/app/tenant-42/inbox");

  await page.getByTestId("open-thread-v3").click();
  const thread = page.getByTestId("staff-thread");
  await expect(thread).toContainText("Hi there");
  await expect(thread).toContainText("Handled in the shared inbox");
  await expect(page.getByTestId("take-over")).toHaveCount(0);
  await expect(page.getByTestId("resume-bot")).toHaveCount(0);

  await page.getByTestId("open-thread-v4").click();
  await expect(thread.getByTestId("open-shared-inbox")).toBeVisible();
  await expect(page.getByTestId("take-over")).toHaveCount(0);
  await expect(page.getByTestId("resume-bot")).toHaveCount(0);
  expect(calls.some((c) => c.method === "POST")).toBe(false);
});

test("conversations: take over and resume post to the conversation and refresh", async ({
  page,
}) => {
  await signedInStaff(page);
  const actions: string[] = [];
  const calls = await mockMany(
    page,
    conversationsHandler((p) => actions.push(p)),
  );
  await page.goto("/platform/instagram/conversations");
  await page.getByTestId("open-thread-v1").click();
  await expect(page.getByTestId("resume-bot")).toHaveCount(0);
  const listCalls = () =>
    calls.filter((c) => c.path === "conversations").length;
  const before = listCalls();
  await page.getByTestId("take-over").click();
  await expect(page.getByText(/You have taken over/)).toBeVisible();
  expect(actions).toEqual(["conversations/v1/take-over"]);
  await expect.poll(listCalls).toBeGreaterThan(before);

  await page.getByTestId("open-thread-v2").click();
  await expect(page.getByTestId("take-over")).toHaveCount(0);
  await page.getByTestId("resume-bot").click();
  await expect(
    page.getByText("Bot resumed for this conversation."),
  ).toBeVisible();
  expect(actions).toEqual([
    "conversations/v1/take-over",
    "conversations/v2/resume-bot",
  ]);
});

test("conversations: status filter narrows the rows", async ({ page }) => {
  await signedInStaff(page);
  await mockMany(page, conversationsHandler());
  await page.goto("/platform/instagram/conversations");
  const table = page.getByTestId("staff-conversations");
  await expect(table).toContainText("omar");
  await page.getByRole("button", { name: "handed off" }).click();
  await expect(table).toContainText("omar");
  await expect(table).not.toContainText("maria");
});

test("conversations: empty, 403 and 502", async ({ page }) => {
  await signedInStaff(page);
  let mode: "empty" | "forbidden" | "down" = "empty";
  await mockMany(page, (path) => {
    if (path !== "conversations") return undefined;
    if (mode === "forbidden") return FORBIDDEN;
    if (mode === "down") return DOWN;
    return { json: [] };
  });
  await page.goto("/platform/instagram/conversations");
  await expect(page.getByTestId("page-empty")).toContainText(
    "No conversations yet",
  );
  mode = "forbidden";
  await page.reload();
  await expect(page.getByTestId("page-forbidden")).toBeVisible();
  mode = "down";
  await page.reload();
  await expect(page.getByTestId("page-unavailable")).toBeVisible();
  mode = "empty";
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("page-empty")).toBeVisible();
});

// ---------------------------------------------------------------- guard

test("a client cannot open any staff Many page, and no Many call is made", async ({
  page,
}) => {
  await registerAdmin(page, "P4D-client");
  let calls = 0;
  await page.route("**/api/v1/many/**", (route) => {
    calls += 1;
    return route.fulfill({ status: 200, json: [] });
  });
  for (const path of [
    "/platform/leads",
    "/platform/messages",
    "/platform/logs",
    "/platform/instagram/conversations",
  ]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login/);
  }
  expect(calls).toBe(0);
});
