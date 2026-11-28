/** Words and tones for Many activity-log events (ported from the old dashboard). Pure. */

export type EventSeverity =
  "success" | "warning" | "error" | "info" | "lifecycle";
export type EventCategory =
  "Campaign" | "Messaging" | "Webhook" | "Account" | "Lead" | "System";

const labelMap: Record<string, string> = {
  account_disconnected: "Instagram account disconnected",
  account_connected: "Instagram account connected",
  account_reconnected: "Instagram account reconnected",
  activated: "Campaign activated",
  archived: "Campaign archived",
  campaign_activated: "Campaign activated",
  campaign_archived: "Campaign archived",
  campaign_created: "Campaign created",
  campaign_paused: "Campaign paused",
  campaign_unarchived: "Campaign unarchived",
  campaign_updated: "Campaign updated",
  campaign_matched: "Campaign matched",
  campaign_deleted: "Campaign deleted",
  campaign_no_match: "No campaign matched",
  campaign_paused_account_disconnected: "Campaign paused",
  campaign_skipped_inactive: "Campaign skipped",
  cooldown_skip: "Cooldown applied",
  created: "Campaign created",
  final_delivery_failed: "Final message failed",
  final_delivery_queued: "Final message queued",
  final_delivery_sent: "Final message sent",
  follow_prompt_delay_started: "Follow prompt delay started",
  follow_prompt_queued: "Follow prompt queued",
  follow_prompt_sent: "Follow prompt sent",
  message_created: "Message queued",
  message_failed: "Message failed",
  message_queued: "Message queued",
  message_render_failed: "Message render failed",
  message_sent: "Message delivered",
  login_failed: "Login failed",
  login_success: "Login success",
  retry_enqueued: "Retry queued",
  triggered: "Campaign triggered",
  updated: "Campaign updated",
  token_expired: "Token expired",
  token_refresh_failed: "Token refresh failed",
  token_refreshed: "Token refreshed",
  webhook_event_failed: "Webhook processing failed",
  webhook_processed: "Webhook processed",
  webhook_received: "Webhook received",
};

const categoryRules: Array<[RegExp, EventCategory]> = [
  [/account|token|reconnect|disconnect/i, "Account"],
  [/message|retry|send|delivery|render/i, "Messaging"],
  [/webhook/i, "Webhook"],
  [/lead/i, "Lead"],
  [
    /campaign|activated|archived|created|updated|triggered|matched|cooldown/i,
    "Campaign",
  ],
];

const severityRules: Array<[RegExp, EventSeverity]> = [
  [/failed|error|expired|render_failed|deleted/i, "error"],
  [/paused|disconnect|cooldown|retry|skipped|warning/i, "warning"],
  [/sent|delivered|reconnected|processed|success/i, "success"],
  [/created|activated|archived|updated/i, "lifecycle"],
  [/webhook|matched|queued|received|info/i, "info"],
];

export const KNOWN_EVENT_TYPES = [
  "webhook_received",
  "webhook_processed",
  "campaign_matched",
  "campaign_deleted",
  "message_queued",
  "message_sent",
  "message_failed",
  "account_disconnected",
  "account_connected",
  "account_reconnected",
  "login_failed",
  "login_success",
  "campaign_paused_account_disconnected",
  "activated",
  "created",
  "updated",
  "archived",
  "campaign_created",
  "campaign_updated",
  "campaign_activated",
  "campaign_paused",
  "campaign_archived",
  "campaign_unarchived",
];

export function eventLabel(eventType?: string | null): string {
  if (!eventType) return "Unknown event";
  return (
    labelMap[eventType] ||
    eventType
      .replaceAll("_", " ")
      .replace(/\b\w/g, (char) => char.toUpperCase())
  );
}

export function eventCategory(eventType?: string | null): EventCategory {
  const value = eventType || "";
  return (
    categoryRules.find(([pattern]) => pattern.test(value))?.[1] || "System"
  );
}

export function eventSeverity(
  eventType?: string | null,
  level?: string | null,
): EventSeverity {
  if (level === "error") return "error";
  if (level === "warning") return "warning";
  const value = eventType || "";
  return severityRules.find(([pattern]) => pattern.test(value))?.[1] || "info";
}

/** Icon names from lib/icons.tsx, one per severity. */
export function eventIconName(
  severity: EventSeverity,
): "check" | "alert" | "info" | "dot" {
  if (severity === "success") return "check";
  if (severity === "error" || severity === "warning") return "alert";
  if (severity === "info") return "info";
  return "dot";
}

export function formatRelativeTime(
  value?: string | null,
  now: number = Date.now(),
): string {
  if (!value) return "Unknown time";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "Unknown time";
  const diff = now - timestamp;
  const abs = Math.abs(diff);
  const suffix = diff >= 0 ? "ago" : "from now";
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (abs < minute) return "Just now";
  if (abs < hour) return `${Math.round(abs / minute)} min ${suffix}`;
  if (abs < day) return `${Math.round(abs / hour)} hours ${suffix}`;
  if (abs < 2 * day && diff >= 0) return "Yesterday";
  if (abs < 7 * day) return `${Math.round(abs / day)} days ${suffix}`;
  return new Date(value).toLocaleDateString();
}

export function formatExactTime(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : "Unknown time";
}

export type EventTypeOption = { label: string; value: string };

/** One option per label; raw types that share a label are sent together, comma separated. */
export function buildEventTypeOptions(eventTypes: string[]): EventTypeOption[] {
  const byLabel = new Map<string, Set<string>>();
  eventTypes.filter(Boolean).forEach((eventType) => {
    const label = eventLabel(eventType);
    if (!byLabel.has(label)) byLabel.set(label, new Set());
    byLabel.get(label)?.add(eventType);
  });
  return Array.from(byLabel.entries())
    .map(([label, values]) => ({
      label,
      value: Array.from(values).sort().join(","),
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export interface LogFilterValues {
  level: string;
  campaign_id: string;
  event_type: string;
  limit: string;
}

/** The server accepts 1 to 500 and defaults to 100; anything else is left out of the query. */
export function effectiveLimit(raw: string): string {
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return "";
  return String(Math.min(500, Math.max(1, n)));
}

/** The query string for GET /logs (same parameter names as the old page). */
export function logsQuery(filters: LogFilterValues): string {
  const params = new URLSearchParams();
  if (filters.level) params.set("level", filters.level);
  if (filters.campaign_id) params.set("campaign_id", filters.campaign_id);
  if (filters.event_type) params.set("event_type", filters.event_type);
  const limit = effectiveLimit(filters.limit);
  if (limit) params.set("limit", limit);
  return params.toString();
}

export function metadataKeyLabel(key: string): string {
  return key
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function metadataValueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "None";
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return String(value);
  return JSON.stringify(value, null, 2);
}
