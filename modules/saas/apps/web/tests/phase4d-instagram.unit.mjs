/* Phase 4D unit tests: the pure Instagram helpers (campaign payloads, keyword sync, labels). */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import Module from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";

function load(relative) {
  const filename = fileURLToPath(new URL(relative, import.meta.url));
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const mod = new Module(filename);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  mod._compile(compiled, filename);
  return mod.exports;
}

const h = load("../lib/many-instagram/helpers.ts");

const campaign = {
  id: "c1",
  instagram_account_id: "a1",
  name: "Summer",
  description: null,
  target_scope: "specific_media",
  target_media_url: "https://www.instagram.com/reel/ABC123/",
  target_media_id: "999",
  target_media_type: "reel",
  target_media_label: "May reel",
  match_type: "exact",
  message_template: "Hi",
  link_url: null,
  cooldown_hours: 24,
  status: "paused",
  delivery_mode: "follow_prompt",
  follow_prompt_title: "Follow us",
  follow_prompt_description: "Please",
  follow_prompt_profile_url: "https://www.instagram.com/x/",
  comment_reply_enabled: true,
  comment_reply_text: "Check DMs",
  ai_enabled: true,
  ai_handoff_after_turns: 5,
  keywords: [
    { id: "k1", campaign_id: "c1", normalized_keyword: "link" },
    { id: "k2", campaign_id: "c1", normalized_keyword: "price" },
  ],
};

test("shortcode: reel, post and tv links; anything else is empty", () => {
  assert.equal(
    h.extractInstagramShortcode("https://www.instagram.com/reel/ABC/"),
    "ABC",
  );
  assert.equal(
    h.extractInstagramShortcode("https://www.instagram.com/p/XYZ/?x=1"),
    "XYZ",
  );
  assert.equal(
    h.extractInstagramShortcode("https://www.instagram.com/tv/T1/"),
    "T1",
  );
  assert.equal(
    h.extractInstagramShortcode("https://www.instagram.com/someone/"),
    "",
  );
  assert.equal(h.extractInstagramShortcode("not a url"), "");
});

test("create body is always a draft and carries the keywords and account", () => {
  const form = { ...h.formFromCampaign(campaign), keywords: ["a", "b"] };
  const body = h.buildCreateBody(form);
  assert.equal(body.status, "draft");
  assert.equal(body.instagram_account_id, "a1");
  assert.deepEqual(body.keywords, ["a", "b"]);
  assert.equal(body.target_media_shortcode, "ABC123");
  assert.equal(body.media_id, null);
});

test("patch body has no account, status or keywords", () => {
  const body = h.buildPatchBody(h.formFromCampaign(campaign));
  assert.equal("instagram_account_id" in body, false);
  assert.equal("status" in body, false);
  assert.equal("keywords" in body, false);
  assert.equal(body.cooldown_hours, 24);
  assert.equal(body.comment_reply_text, "Check DMs");
});

test("any-media scope clears the media fields; instant mode clears the follow prompt", () => {
  const form = {
    ...h.formFromCampaign(campaign),
    target_scope: "any_media",
    delivery_mode: "instant",
    comment_reply_enabled: false,
  };
  const body = h.buildPatchBody(form);
  assert.equal(body.target_media_id, null);
  assert.equal(body.target_media_url, null);
  assert.equal(body.target_media_type, "unknown");
  assert.equal(body.follow_prompt_title, null);
  assert.equal(body.comment_reply_text, null);
});

test("handoff turns fall back to 8 and cooldown is a number", () => {
  const form = {
    ...h.formFromCampaign(),
    ai_handoff_after_turns: 0,
    cooldown_hours: "12",
  };
  const body = h.buildPatchBody(form);
  assert.equal(body.ai_handoff_after_turns, 8);
  assert.equal(body.cooldown_hours, 12);
});

test("keyword sync adds new keywords and removes dropped ones by id", () => {
  const plan = h.planKeywordSync(campaign.keywords, ["link", "sale"]);
  assert.deepEqual(plan.add, ["sale"]);
  assert.deepEqual(plan.remove, ["k2"]);
  assert.deepEqual(h.planKeywordSync(campaign.keywords, ["link", "price"]), {
    add: [],
    remove: [],
  });
});

test("keyword add path puts the keyword in the query, encoded", () => {
  assert.equal(
    h.keywordAddPath("c1", "a b&c"),
    "/campaigns/c1/keywords?keyword=a%20b%26c",
  );
});

test("addKeyword trims, ignores blanks and duplicates", () => {
  assert.deepEqual(h.addKeyword(["a"], "  b "), ["a", "b"]);
  assert.deepEqual(h.addKeyword(["a"], "a"), ["a"]);
  assert.deepEqual(h.addKeyword(["a"], "   "), ["a"]);
});

test("draft campaigns count as paused in filters and counts", () => {
  const rows = [
    { status: "draft" },
    { status: "paused" },
    { status: "active" },
    { status: "archived" },
  ];
  assert.equal(h.campaignUiStatus("draft"), "paused");
  assert.deepEqual(h.campaignFilterCounts(rows), {
    all: 4,
    active: 1,
    paused: 2,
    archived: 1,
  });
  assert.equal(h.filterCampaigns(rows, "paused").length, 2);
  assert.equal(h.filterCampaigns(rows, "all").length, 4);
});

test("target label", () => {
  assert.equal(
    h.targetLabel({ target_scope: "any_media", target_media_type: "unknown" }),
    "Any media",
  );
  assert.equal(
    h.targetLabel({
      target_scope: "specific_media",
      target_media_type: "reel",
      target_media_label: "May",
    }),
    "Reel · May",
  );
  assert.equal(
    h.targetLabel({
      target_scope: "specific_media",
      target_media_type: "unknown",
    }),
    "Instagram post · Instagram post",
  );
});

test("permanent delete needs the typed phrase", () => {
  assert.equal(h.deleteConfirmText(["Summer"]), "delete Summer");
  assert.equal(h.deleteConfirmText(["a", "b"]), "delete campaigns");
  assert.equal(h.deleteConfirmed(" DELETE summer ", ["Summer"]), true);
  assert.equal(h.deleteConfirmed("delete", ["Summer"]), false);
  assert.equal(h.deleteConfirmed("delete campaigns", []), false);
});

test("token expiry status", () => {
  const now = Date.parse("2026-11-26T00:00:00Z");
  const day = 86400000;
  const at = (days) => new Date(now + days * day).toISOString();
  assert.equal(
    h.expiryStatus({ status: "disconnected", expires_at: at(30) }, now),
    "disconnected",
  );
  assert.equal(h.expiryStatus({ status: "connected" }, now), "connected");
  assert.equal(
    h.expiryStatus({ status: "connected", expires_at: at(-1) }, now),
    "reconnect_required",
  );
  assert.equal(
    h.expiryStatus({ status: "connected", expires_at: at(3) }, now),
    "expiring_soon",
  );
  assert.equal(
    h.expiryStatus({ status: "connected", expires_at: at(30) }, now),
    "connected",
  );
});

test("connected means status connected or missing", () => {
  assert.equal(h.isConnected({ status: "connected" }), true);
  assert.equal(h.isConnected({}), true);
  assert.equal(h.isConnected({ status: "disconnected" }), false);
});

test("media path and labels", () => {
  assert.equal(h.mediaPath("a1"), "/instagram/accounts/a1/media?limit=24");
  assert.equal(
    h.mediaPath("a1", "cur/sor"),
    "/instagram/accounts/a1/media?limit=24&after=cur%2Fsor",
  );
  assert.equal(h.mediaTypeLabel("VIDEO"), "Reel/Video");
  assert.equal(h.mediaTypeLabel("CAROUSEL_ALBUM"), "Carousel");
  assert.equal(h.mediaTypeLabel("IMAGE"), "Post");
});

test("only https OAuth addresses are followed", () => {
  assert.equal(
    h.safeOauthUrl("https://www.facebook.com/dialog/oauth?x=1"),
    "https://www.facebook.com/dialog/oauth?x=1",
  );
  assert.equal(h.safeOauthUrl("http://evil.example/"), null);
  assert.equal(h.safeOauthUrl("javascript:alert(1)"), null);
  assert.equal(h.safeOauthUrl(undefined), null);
});

test("failed message ids and date fallback", () => {
  assert.deepEqual(
    h.failedMessageIds([
      { id: "m1", status: "failed" },
      { id: "m2", status: "sent" },
    ]),
    ["m1"],
  );
  assert.equal(h.formatDateTime(null), "Unknown");
  assert.equal(h.formatDateTime("garbage"), "Unknown");
});
