/**
 * Pure helpers for the Instagram pages: no React, no network. Covered by
 * tests/phase4d-instagram.unit.mjs.
 */
import type {
  Campaign,
  CampaignCreateBody,
  CampaignPatchBody,
  CampaignStatus,
  DeliveryMode,
  InstagramAccount,
  MatchType,
  TargetMediaType,
  TargetScope,
} from "./types";

/** The form's working copy of a campaign. */
export interface CampaignFormState {
  name: string;
  description: string;
  instagram_account_id: string;
  target_scope: TargetScope;
  target_media_url: string;
  target_media_id: string;
  target_media_shortcode: string;
  target_media_type: TargetMediaType;
  target_media_label: string;
  keywords: string[];
  keywordInput: string;
  match_type: MatchType;
  message_template: string;
  link_url: string;
  cooldown_hours: number;
  delivery_mode: DeliveryMode;
  follow_prompt_title: string;
  follow_prompt_description: string;
  follow_prompt_profile_url: string;
  comment_reply_enabled: boolean;
  comment_reply_text: string;
  ai_enabled: boolean;
  ai_handoff_after_turns: number;
}

export const TEMPLATE_VARIABLES = [
  "{{username}}",
  "{{campaign_name}}",
  "{{keyword}}",
  "{{link}}",
  "{{media_url}}",
] as const;

/** The shortcode in an instagram.com /p/, /reel/ or /tv/ link, or "". */
export function extractInstagramShortcode(value: string): string {
  try {
    const url = new URL(value);
    const parts = url.pathname.split("/").filter(Boolean);
    return ["reel", "p", "tv"].includes(parts[0]) && parts[1] ? parts[1] : "";
  } catch {
    return "";
  }
}

export function formFromCampaign(campaign?: Campaign): CampaignFormState {
  return {
    name: campaign?.name || "",
    description: campaign?.description || "",
    instagram_account_id: campaign?.instagram_account_id || "",
    target_scope: campaign?.target_scope || "any_media",
    target_media_url: campaign?.target_media_url || campaign?.media_url || "",
    target_media_id: campaign?.target_media_id || "",
    target_media_shortcode: campaign?.target_media_shortcode || "",
    target_media_type: campaign?.target_media_type || "unknown",
    target_media_label: campaign?.target_media_label || "",
    keywords:
      campaign?.keywords.map((keyword) => keyword.normalized_keyword) || [],
    keywordInput: "",
    match_type: campaign?.match_type || "contains",
    message_template:
      campaign?.message_template ||
      "Hi {{username}}, here is your {{keyword}} link: {{link}}",
    link_url: campaign?.link_url || "",
    cooldown_hours: campaign?.cooldown_hours ?? 168,
    delivery_mode: campaign?.delivery_mode || "instant",
    follow_prompt_title: campaign?.follow_prompt_title || "",
    follow_prompt_description: campaign?.follow_prompt_description || "",
    follow_prompt_profile_url: campaign?.follow_prompt_profile_url || "",
    comment_reply_enabled: campaign?.comment_reply_enabled ?? false,
    comment_reply_text:
      campaign?.comment_reply_text || "Check your DMs \u{1F4E9}",
    ai_enabled: campaign?.ai_enabled ?? false,
    ai_handoff_after_turns: campaign?.ai_handoff_after_turns ?? 8,
  };
}

/** The editable fields as the PATCH body (the same fields the old editor sent). */
export function buildPatchBody(form: CampaignFormState): CampaignPatchBody {
  const specific = form.target_scope === "specific_media";
  const url = specific ? form.target_media_url || null : null;
  return {
    name: form.name,
    description: form.description || null,
    media_id: null,
    media_url: url,
    target_scope: form.target_scope,
    target_media_url: url,
    target_media_shortcode: specific
      ? extractInstagramShortcode(form.target_media_url) || null
      : null,
    target_media_id: specific ? form.target_media_id || null : null,
    target_media_type: specific ? form.target_media_type : "unknown",
    target_media_label: specific ? form.target_media_label || null : null,
    match_type: form.match_type,
    message_template: form.message_template,
    link_url: form.link_url || null,
    cooldown_hours: Number(form.cooldown_hours),
    delivery_mode: form.delivery_mode,
    follow_prompt_title:
      form.delivery_mode === "follow_prompt" ? form.follow_prompt_title : null,
    follow_prompt_description:
      form.delivery_mode === "follow_prompt"
        ? form.follow_prompt_description
        : null,
    follow_prompt_profile_url:
      form.delivery_mode === "follow_prompt"
        ? form.follow_prompt_profile_url
        : null,
    comment_reply_enabled: form.comment_reply_enabled,
    comment_reply_text: form.comment_reply_enabled
      ? form.comment_reply_text || null
      : null,
    ai_enabled: form.ai_enabled,
    ai_handoff_after_turns: Number(form.ai_handoff_after_turns) || 8,
  };
}

/** The POST /campaigns body: always a draft; activation is a separate call. */
export function buildCreateBody(form: CampaignFormState): CampaignCreateBody {
  return {
    instagram_account_id: form.instagram_account_id,
    ...buildPatchBody(form),
    status: "draft",
    keywords: form.keywords,
  };
}

/** Keywords to add and keywords (by id) to remove so the campaign matches `desired`. */
export function planKeywordSync(
  existing: { id: string; normalized_keyword: string }[],
  desired: string[],
): { add: string[]; remove: string[] } {
  const current = new Set(
    existing.map((keyword) => keyword.normalized_keyword),
  );
  const wanted = new Set(desired);
  return {
    add: desired.filter((keyword) => !current.has(keyword)),
    remove: existing
      .filter((keyword) => !wanted.has(keyword.normalized_keyword))
      .map((keyword) => keyword.id),
  };
}

/** The path (with the keyword in the query, as Many expects) that adds a keyword. */
export function keywordAddPath(campaignId: string, keyword: string): string {
  return `/campaigns/${campaignId}/keywords?keyword=${encodeURIComponent(keyword)}`;
}

/** Add a keyword if it is non-empty and new. */
export function addKeyword(keywords: string[], input: string): string[] {
  const keyword = input.trim();
  if (!keyword || keywords.includes(keyword)) return keywords;
  return [...keywords, keyword];
}

export type CampaignUiStatus = "active" | "paused" | "archived";

/** Drafts are shown as paused, like the old list. */
export function campaignUiStatus(status: CampaignStatus): CampaignUiStatus {
  return status === "archived" || status === "active" ? status : "paused";
}

export type CampaignFilter = "all" | CampaignUiStatus;

export function filterCampaigns<T extends { status: CampaignStatus }>(
  campaigns: T[],
  filter: CampaignFilter,
): T[] {
  if (filter === "all") return campaigns;
  return campaigns.filter((c) => campaignUiStatus(c.status) === filter);
}

export function campaignFilterCounts(
  campaigns: { status: CampaignStatus }[],
): Record<CampaignFilter, number> {
  return {
    all: campaigns.length,
    active: filterCampaigns(campaigns, "active").length,
    paused: filterCampaigns(campaigns, "paused").length,
    archived: filterCampaigns(campaigns, "archived").length,
  };
}

/** "Post · label", "Reel · label" or "Any media". */
export function targetLabel(campaign: {
  target_scope: TargetScope;
  target_media_type: TargetMediaType;
  target_media_label?: string | null;
}): string {
  if (campaign.target_scope !== "specific_media") return "Any media";
  const type =
    campaign.target_media_type && campaign.target_media_type !== "unknown"
      ? campaign.target_media_type.charAt(0).toUpperCase() +
        campaign.target_media_type.slice(1)
      : "Instagram post";
  const fallback =
    campaign.target_media_type === "reel" ? "Instagram reel" : "Instagram post";
  return `${type} · ${campaign.target_media_label || fallback}`;
}

/** The text a person types to confirm a permanent delete. */
export function deleteConfirmText(names: string[]): string {
  return names.length === 1 ? `delete ${names[0]}` : "delete campaigns";
}

export function deleteConfirmed(typed: string, names: string[]): boolean {
  return (
    names.length > 0 &&
    typed.trim().toLowerCase() === deleteConfirmText(names).toLowerCase()
  );
}

/** The account's state for the list: token expiry decides it. */
export function expiryStatus(
  account: Pick<InstagramAccount, "status" | "expires_at">,
  now: number = Date.now(),
): "disconnected" | "connected" | "reconnect_required" | "expiring_soon" {
  if (account.status === "disconnected") return "disconnected";
  if (!account.expires_at) return "connected";
  const days = (new Date(account.expires_at).getTime() - now) / 86400000;
  if (Number.isNaN(days)) return "connected";
  if (days < 0) return "reconnect_required";
  if (days <= 7) return "expiring_soon";
  return "connected";
}

export function isConnected(account: Pick<InstagramAccount, "status">) {
  return account.status === "connected" || !account.status;
}

export function mediaTypeLabel(mediaType: string): string {
  switch (mediaType) {
    case "VIDEO":
      return "Reel/Video";
    case "CAROUSEL_ALBUM":
      return "Carousel";
    default:
      return "Post";
  }
}

/** The media list path (24 per page, a cursor for the next). */
export function mediaPath(
  accountId: string,
  cursor?: string | null,
  limit = 24,
): string {
  const query = cursor
    ? `?limit=${limit}&after=${encodeURIComponent(cursor)}`
    : `?limit=${limit}`;
  return `/instagram/accounts/${encodeURIComponent(accountId)}/media${query}`;
}

/** Only follow an https OAuth address; anything else is refused. */
export function safeOauthUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function formatDateTime(value?: string | null): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

/** Ids of the recent messages that failed (the stats page retries these). */
export function failedMessageIds(
  messages: { id: string; status: string }[],
): string[] {
  return messages.filter((m) => m.status === "failed").map((m) => m.id);
}
