/* Phase 4D unit tests: the pure helpers of the staff Many pages (leads, messages, logs, conversations). */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import Module from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";

function load(filename) {
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const mod = new Module(filename);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const realRequire = mod.require.bind(mod);
  mod.require = (id) => {
    if (id.startsWith("./")) {
      return load(path.join(path.dirname(filename), `${id.slice(2)}.ts`));
    }
    return realRequire(id);
  };
  mod._compile(compiled, filename);
  return mod.exports;
}

const dir = (name) =>
  fileURLToPath(new URL(`../lib/many-staff/${name}.ts`, import.meta.url));
const grouping = load(dir("log-grouping"));
const events = load(dir("event-presentation"));
const leads = load(dir("leads"));
const messages = load(dir("messages"));
const convs = load(dir("conversations"));
const paging = load(dir("paging"));

const log = (id, event_type, metadata = {}, extra = {}) => ({
  id,
  level: "info",
  event_type,
  message: id,
  metadata,
  ...extra,
});

test("groupLogFlow joins consecutive flow events that share a comment", () => {
  const groups = grouping.groupLogFlow([
    log("a", "webhook_received", { comment_id: "c1" }),
    log("b", "campaign_matched", { comment_id: "c1" }),
    log("c", "message_sent", { comment_id: "c1" }),
    log("d", "message_sent", { comment_id: "c2" }),
  ]);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].kind, "group");
  assert.deepEqual(
    groups[0].logs.map((l) => l.id),
    ["a", "b", "c"],
  );
  assert.equal(groups[0].id, "a-b-c");
  assert.equal(groups[1].kind, "single");
});

test("groupLogFlow leaves non-flow events and events without a key alone", () => {
  const groups = grouping.groupLogFlow([
    log("a", "login_success", { comment_id: "c1" }),
    log("b", "message_sent", {}),
    log("c", "message_sent", {}),
    log("d", "message_sent", {}, { campaign_id: "k" }),
    log("e", "message_failed", {}, { campaign_id: "k" }),
  ]);
  assert.deepEqual(
    groups.map((g) => [g.kind, g.logs.length]),
    [
      ["single", 1],
      ["single", 1],
      ["single", 1],
      ["group", 2],
    ],
  );
  assert.deepEqual(grouping.groupLogFlow([]), []);
});

test("event labels, categories and severities", () => {
  assert.equal(events.eventLabel("message_sent"), "Message delivered");
  assert.equal(events.eventLabel("some_new_thing"), "Some New Thing");
  assert.equal(events.eventLabel(null), "Unknown event");
  assert.equal(events.eventCategory("token_expired"), "Account");
  assert.equal(events.eventCategory("webhook_received"), "Webhook");
  assert.equal(events.eventCategory("zzz"), "System");
  assert.equal(events.eventSeverity("message_sent", "error"), "error");
  assert.equal(events.eventSeverity("message_sent", "warning"), "warning");
  assert.equal(events.eventSeverity("message_failed", "info"), "error");
  assert.equal(events.eventSeverity("message_sent", "info"), "success");
  assert.equal(events.eventSeverity("zzz", null), "info");
  assert.equal(events.eventIconName("success"), "check");
  assert.equal(events.eventIconName("error"), "alert");
});

test("event type options merge raw types that share a label", () => {
  const options = events.buildEventTypeOptions([
    "created",
    "campaign_created",
    "message_sent",
    "",
  ]);
  const created = options.find((o) => o.label === "Campaign created");
  assert.equal(created.value, "campaign_created,created");
  assert.equal(options.length, 2);
  assert.deepEqual(
    options.map((o) => o.label),
    [...options.map((o) => o.label)].sort(),
  );
});

test("logsQuery sends only set filters and clamps the limit to 1..500", () => {
  const base = { level: "", campaign_id: "", event_type: "", limit: "100" };
  assert.equal(events.logsQuery(base), "limit=100");
  assert.equal(
    events.logsQuery({
      level: "error",
      campaign_id: "k1",
      event_type: "a,b",
      limit: "9999",
    }),
    "level=error&campaign_id=k1&event_type=a%2Cb&limit=500",
  );
  assert.equal(events.logsQuery({ ...base, limit: "0" }), "limit=1");
  assert.equal(events.logsQuery({ ...base, limit: "" }), "");
});

test("relative time", () => {
  const now = Date.parse("2026-01-10T12:00:00Z");
  const at = (ms) => new Date(now - ms).toISOString();
  assert.equal(events.formatRelativeTime(at(10_000), now), "Just now");
  assert.equal(events.formatRelativeTime(at(5 * 60_000), now), "5 min ago");
  assert.equal(
    events.formatRelativeTime(at(3 * 3_600_000), now),
    "3 hours ago",
  );
  assert.equal(events.formatRelativeTime(at(30 * 3_600_000), now), "Yesterday");
  assert.equal(
    events.formatRelativeTime(at(3 * 86_400_000), now),
    "3 days ago",
  );
  assert.equal(events.formatRelativeTime(null, now), "Unknown time");
  assert.equal(events.formatRelativeTime("nope", now), "Unknown time");
});

test("metadata display helpers", () => {
  assert.equal(events.metadataKeyLabel("comment_id"), "Comment Id");
  assert.equal(events.metadataValueText(null), "None");
  assert.equal(events.metadataValueText(""), "None");
  assert.equal(events.metadataValueText(0), "0");
  assert.equal(events.metadataValueText({ a: 1 }), '{\n  "a": 1\n}');
});

test("leadsQuery uses the old parameter names; platform stays client-side", () => {
  const none = { campaignId: "", accountId: "", platform: "", search: "" };
  assert.equal(leads.leadsQuery(none), "");
  assert.equal(
    leads.leadsQuery({
      campaignId: "c1",
      accountId: "a1",
      platform: "whatsapp",
      search: " mo ",
    }),
    "campaign_id=c1&instagram_account_id=a1&search=mo",
  );
  const rows = [
    { id: "1", platform: "instagram" },
    { id: "2", platform: "whatsapp" },
  ];
  assert.deepEqual(
    leads.filterLeadsByPlatform(rows, "whatsapp").map((r) => r.id),
    ["2"],
  );
  assert.equal(leads.filterLeadsByPlatform(rows, "").length, 2);
});

test("lead labels", () => {
  assert.equal(
    leads.leadAccountName({ whatsapp_account_username: "+1" }),
    "+1",
  );
  assert.equal(leads.leadAccountName({}), "Unknown account");
  assert.equal(leads.leadCampaignLabel({ lead_source: "cold_dm" }), "Cold DM");
  assert.equal(
    leads.leadCampaignLabel({ source_campaign: "Spring" }),
    "Spring",
  );
  assert.equal(leads.leadCampaignLabel({}), "Unknown campaign");
  assert.equal(leads.leadSourceLabel("cold_dm"), "Cold DM");
});

test("message helpers treat the string None as no campaign", () => {
  assert.equal(messages.hasCampaign("None"), false);
  assert.equal(messages.hasCampaign(null), false);
  assert.equal(messages.hasCampaign("c1"), true);
  assert.equal(messages.campaignLabel("None", {}), "Cold DM");
  assert.equal(messages.campaignLabel("c1", { c1: "Spring" }), "Spring");
  assert.equal(messages.campaignLabel("c2", {}), "c2");
  assert.equal(messages.messageTypeLabel("follow_prompt"), "Follow prompt");
  assert.equal(messages.messageTypeLabel(undefined), "Final delivery");
  assert.equal(messages.retriesLabel(1), "1 retry");
  assert.equal(messages.retriesLabel(2), "2 retries");
  assert.equal(messages.canRetry({ status: "failed", retryable: true }), true);
  assert.equal(
    messages.canRetry({ status: "failed", retryable: false }),
    false,
  );
  assert.equal(messages.canRetry({ status: "sent", retryable: true }), false);
});

test("a delegated conversation never gets Take over or Resume bot", () => {
  assert.deepEqual(
    convs.conversationControl({ managed_by_saas: true, status: "bot_active" }),
    { kind: "shared_inbox", href: null },
  );
  assert.deepEqual(
    convs.conversationControl({
      managed_by_saas: true,
      status: "handed_off",
      tenant_id: "t 1",
    }),
    { kind: "shared_inbox", href: "/app/t%201/inbox" },
  );
  assert.deepEqual(
    convs.conversationControl({
      managed_by_saas: true,
      status: "closed",
      tenant_id: "  ",
    }),
    { kind: "shared_inbox", href: null },
  );
  assert.deepEqual(convs.conversationControl({ status: "bot_active" }), {
    kind: "take_over",
  });
  assert.deepEqual(
    convs.conversationControl({ managed_by_saas: false, status: "handed_off" }),
    { kind: "resume_bot" },
  );
});

test("conversation filters", () => {
  const rows = [
    { id: "1", status: "bot_active", platform: "instagram" },
    { id: "2", status: "closed", platform: "instagram" },
    { id: "3", status: "bot_active", platform: "facebook" },
  ];
  const ids = (s, p) => convs.filterConversations(rows, s, p).map((r) => r.id);
  assert.deepEqual(ids("all", "all"), ["1", "2", "3"]);
  assert.deepEqual(ids("bot_active", "all"), ["1", "3"]);
  assert.deepEqual(ids("bot_active", "facebook"), ["3"]);
});

test("paginate clamps and reports the visible range", () => {
  const items = Array.from({ length: 120 }, (_, i) => i);
  const first = paging.paginate(items, 1);
  assert.equal(first.rows.length, 50);
  assert.equal(first.pageCount, 3);
  assert.equal(first.from, 1);
  assert.equal(first.to, 50);
  const last = paging.paginate(items, 99);
  assert.equal(last.page, 3);
  assert.equal(last.rows.length, 20);
  assert.equal(last.from, 101);
  assert.equal(last.to, 120);
  const empty = paging.paginate([], 1);
  assert.deepEqual([empty.pageCount, empty.from, empty.to], [1, 0, 0]);
  assert.equal(paging.paginate(items, 0).page, 1);
});
