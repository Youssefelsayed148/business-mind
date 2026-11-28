import { expect, test, type Page } from "@playwright/test";

import { registerAdmin, uniqueEmail } from "./e2e-helpers";
import { promoteToStaff } from "./staff-helpers";

/**
 * Phase 4F: walks every migrated Many page, in a wide and a phone-sized window, once with
 * Arabic content in the data and once with the document forced right to left. The Many calls
 * are answered by Playwright with synthetic data (no Many process here), so this proves layout
 * and bidi behaviour, not the real Many answers.
 *
 * Checks per page: it renders a heading, nothing throws in the browser, no horizontal page
 * scroll. Screenshots are written to test-results/phase4f/ (not committed).
 */

const AR = "عرض الربيع الكبير";
const AR_PERSON = "دانا كوهين";
const AR_TEXT = "مرحبا، شكرا لتواصلكم معنا. سنرد عليكم قريبا";
const AR_MIXED = "طلب رقم 1042 من shop_ig";

/** One row that carries every field a list page might read, in Arabic and mixed text. */
const ROW = {
  id: "r-1",
  name: AR,
  title: AR,
  username: "shop_ig",
  display_name: AR_PERSON,
  display_phone_number: "+971 50 000 0000",
  phone_number_id: "111",
  wa_id: "971500000000",
  ig_user_id: "1001",
  status: "active",
  platform: "whatsapp",
  channel: "instagram",
  language: "ar",
  category: "marketing",
  keyword: "السعر",
  message: AR_TEXT,
  text: AR_TEXT,
  body: AR_TEXT,
  content: AR_MIXED,
  event_type: "message_sent",
  level: "info",
  source_campaign: AR,
  lead_source: "campaign",
  marketing_consent: "unknown",
  whatsapp_account_id: "acc-1",
  template_id: "t-1",
  components: [{ type: "BODY", text: AR_TEXT }],
  throttle_per_minute: 30,
  total_recipients: 10,
  sent_count: 4,
  delivered_count: 3,
  read_count: 2,
  failed_count: 1,
  skipped_count: 2,
  keywords: [
    { id: "k1", campaign_id: "r-1", normalized_keyword: "السعر", created_at: "2026-05-01T10:00:00Z" },
  ],
  recent_messages: [],
  recent_logs: [],
  created_at: "2026-05-01T10:00:00Z",
  captured_at: "2026-05-01T10:00:00Z",
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

function answer(path: string): unknown {
  if (/outreach-health$/.test(path)) return HEALTH;
  if (/stats\/overview$/.test(path))
    return {
      total_messages: 120,
      total_leads: 14,
      active_campaigns: 2,
      messages_by_day: [],
    };
  if (/staff\/campaigns\/[^/]+\/stats$/.test(path))
    return {
      ...ROW,
      campaign_id: "cmp-1",
      keywords: ["السعر", "price"],
      target_scope: "any_media",
      target_media_type: "post",
      match_type: "contains",
      delivery_mode: "instant",
      message_template: AR_TEXT,
      cooldown_hours: 24,
      total_triggers: 3,
      successful_sends: 2,
      failed_sends: 1,
    };
  if (/\/stats$/.test(path))
    return {
      campaign: ROW,
      recipient_statuses: { sent: 4 },
      reasons: {},
      row_count: 10,
    };
  if (/facebook\/campaigns(\?|$)/.test(path))
    return [{ ...ROW, keywords: ["السعر", "price"] }];
  if (/whatsapp\/contacts(\?|$)/.test(path))
    return { items: [ROW, { ...ROW, id: "r-2", display_name: AR }], total: 2 };
  if (/instagram\/accounts\/[^/]+\/media/.test(path)) return { media: [] };
  if (/(campaigns|conversations|messages)\/[^/?]+$/.test(path)) return ROW;
  return [ROW, { ...ROW, id: "r-2", name: AR_PERSON }];
}

async function mockMany(page: Page) {
  await page.route("**/api/v1/many/**", (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^.*\/api\/v1\/many\//, "");
    if (route.request().method() !== "GET")
      return route.fulfill({ json: ROW });
    return route.fulfill({ json: answer(path) });
  });
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow, "page scrolls sideways").toBeLessThanOrEqual(1);
}

/**
 * Arabic text that came from the data must decide its own direction (dir="auto" on it or on a
 * wrapper), so that a left-to-right page does not scramble it. Returns a short description of
 * every element that holds Arabic text without such a wrapper. Options, inputs and the page's
 * own fixed words are out of scope.
 */
async function arabicWithoutOwnDirection(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const arabic = /[\u0600-\u06FF]/;
    const offenders: string[] = [];
    const walker = document.createTreeWalker(
      document.querySelector("main") ?? document.body,
      NodeFilter.SHOW_TEXT,
    );
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!arabic.test(node.textContent ?? "")) continue;
      const el = node.parentElement;
      if (!el || el.closest("option, textarea, input, script, style")) continue;
      if (el.closest('[dir="auto"], [dir="rtl"], [dir="ltr"]')) continue;
      const hidden = el.closest("[hidden], [aria-hidden='true']");
      if (hidden) continue;
      offenders.push(`${el.tagName.toLowerCase()}.${el.className}: ${(node.textContent ?? "").trim().slice(0, 30)}`);
    }
    return offenders;
  });
}

const STAFF_PAGES = [
  "/platform/many",
  "/platform/instagram/accounts",
  "/platform/instagram/campaigns",
  "/platform/instagram/campaigns/new",
  "/platform/instagram/campaigns/cmp-1",
  "/platform/instagram/campaigns/cmp-1/stats",
  "/platform/instagram/conversations",
  "/platform/leads",
  "/platform/messages",
  "/platform/logs",
];
const CLIENT_PAGES = [
  "whatsapp",
  "whatsapp/contacts",
  "whatsapp/templates",
  "whatsapp/campaigns",
  "whatsapp/campaigns/new",
  "whatsapp/campaigns/cp-1",
  "whatsapp/health",
  "channels",
  "facebook/campaigns",
];

const MODES = [
  { name: "wide", size: { width: 1280, height: 800 }, rtl: false },
  { name: "phone", size: { width: 390, height: 800 }, rtl: false },
  { name: "wide-rtl", size: { width: 1280, height: 800 }, rtl: true },
  { name: "phone-rtl", size: { width: 390, height: 800 }, rtl: true },
];

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

async function visit(
  page: Page,
  route: string,
  mode: (typeof MODES)[number],
  errors: string[],
) {
  await page.setViewportSize(mode.size);
  await page.goto(route);
  if (mode.rtl) await page.evaluate(() => (document.documentElement.dir = "rtl"));
  await expect(page.getByRole("heading").first()).toBeVisible();
  // Let the page's own data calls settle before the picture is taken.
  await page.waitForLoadState("networkidle");
  await noHorizontalScroll(page);
  expect
    .soft(await arabicWithoutOwnDirection(page), `Arabic without dir on ${route}`)
    .toEqual([]);
  const name = `${route.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "")}-${mode.name}`;
  await page.screenshot({
    path: `test-results/phase4f/${name}.png`,
    fullPage: true,
  });
  expect.soft(errors, `browser errors on ${route}`).toEqual([]);
  errors.length = 0;
}

test("walk: every staff Many page, wide and phone, left to right and right to left", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const errors: string[] = [];
  const email = uniqueEmail("p4f-staff");
  await registerAdmin(page, "P4F", { email });
  promoteToStaff(email);
  // Listen only after sign-in: the signed-out login page answers 401 to its own session probe.
  page.on("pageerror", (e) => errors.push(`${e.message} :: ${String(e.stack).split("\n").slice(1, 3).join(" ")}`));
  await mockMany(page);
  for (const mode of MODES)
    for (const route of STAFF_PAGES) await visit(page, route, mode, errors);
});

test("walk: every client Many page, wide and phone, left to right and right to left", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const errors: string[] = [];
  const { tenantId } = await registerAdmin(page, "P4F");
  page.on("pageerror", (e) => errors.push(`${e.message} :: ${String(e.stack).split("\n").slice(1, 3).join(" ")}`));
  await mockMany(page);
  for (const mode of MODES)
    for (const route of CLIENT_PAGES)
      await visit(page, `/app/${tenantId}/${route}`, mode, errors);
});
