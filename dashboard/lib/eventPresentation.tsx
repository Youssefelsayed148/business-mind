import type { ComponentType } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  PauseCircle,
  PlugZap,
  PlusCircle,
  Rocket,
  RotateCcw,
  Send,
  Target,
  Trash2,
  Unplug,
  UserPlus,
  Webhook,
} from "lucide-react";

export type EventSeverity = "success" | "warning" | "error" | "info" | "lifecycle";
export type EventCategory = "Campaign" | "Messaging" | "Webhook" | "Account" | "Lead" | "System";

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
  webhook_processed: "Webhook processed",
  webhook_received: "Webhook received",
};

const categoryRules: Array<[RegExp, EventCategory]> = [
  [/account|token|reconnect|disconnect/i, "Account"],
  [/message|retry|send|delivery|render/i, "Messaging"],
  [/webhook/i, "Webhook"],
  [/lead/i, "Lead"],
  [/campaign|activated|archived|created|updated|triggered|matched|cooldown/i, "Campaign"],
];

const severityRules: Array<[RegExp, EventSeverity]> = [
  [/failed|error|expired|render_failed|deleted/i, "error"],
  [/paused|disconnect|cooldown|retry|skipped|warning/i, "warning"],
  [/sent|delivered|reconnected|processed|success/i, "success"],
  [/created|activated|archived|updated/i, "lifecycle"],
  [/webhook|matched|queued|received|info/i, "info"],
];

const iconRules: Array<[RegExp, ComponentType<{ className?: string }>]> = [
  [/message_sent|delivered/i, CheckCircle2],
  [/message_failed|failed|error/i, AlertTriangle],
  [/account_disconnected|disconnect/i, Unplug],
  [/account_reconnected|reconnect/i, PlugZap],
  [/activated/i, Rocket],
  [/paused/i, PauseCircle],
  [/webhook/i, Webhook],
  [/matched|triggered/i, Target],
  [/lead/i, UserPlus],
  [/deleted/i, Trash2],
  [/created/i, PlusCircle],
  [/retry/i, RotateCcw],
  [/message|queued/i, Send],
];

export const severityStyles: Record<EventSeverity, {
  border: string;
  icon: string;
  iconWrap: string;
  chip: string;
  badge: string;
}> = {
  success: {
    border: "border-l-emerald-500",
    icon: "text-emerald-700",
    iconWrap: "border-emerald-200 bg-emerald-50",
    chip: "border-emerald-200 bg-emerald-50 text-emerald-700",
    badge: "border-emerald-200 bg-emerald-50 text-emerald-700",
  },
  warning: {
    border: "border-l-amber-500",
    icon: "text-amber-700",
    iconWrap: "border-amber-200 bg-amber-50",
    chip: "border-amber-200 bg-amber-50 text-amber-700",
    badge: "border-amber-200 bg-amber-50 text-amber-700",
  },
  error: {
    border: "border-l-red-500",
    icon: "text-red-700",
    iconWrap: "border-red-200 bg-red-50",
    chip: "border-red-200 bg-red-50 text-red-700",
    badge: "border-red-200 bg-red-50 text-red-700",
  },
  info: {
    border: "border-l-sky-500",
    icon: "text-sky-700",
    iconWrap: "border-sky-200 bg-sky-50",
    chip: "border-sky-200 bg-sky-50 text-sky-700",
    badge: "border-sky-200 bg-sky-50 text-sky-700",
  },
  lifecycle: {
    border: "border-l-violet-500",
    icon: "text-violet-700",
    iconWrap: "border-violet-200 bg-violet-50",
    chip: "border-violet-200 bg-violet-50 text-violet-700",
    badge: "border-violet-200 bg-violet-50 text-violet-700",
  },
};

export function eventLabel(eventType?: string | null) {
  if (!eventType) return "Unknown event";
  return labelMap[eventType] || eventType.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function eventCategory(eventType?: string | null): EventCategory {
  const value = eventType || "";
  return categoryRules.find(([pattern]) => pattern.test(value))?.[1] || "System";
}

export function eventSeverity(eventType?: string | null, level?: string | null): EventSeverity {
  if (level === "error") return "error";
  if (level === "warning") return "warning";
  const value = eventType || "";
  return severityRules.find(([pattern]) => pattern.test(value))?.[1] || "info";
}

export function EventIcon({ eventType, className = "" }: { eventType?: string | null; className?: string }) {
  const Icon = iconRules.find(([pattern]) => pattern.test(eventType || ""))?.[1] || CircleDot;
  return <Icon className={className} aria-hidden="true" />;
}

export function formatRelativeTime(value?: string | null) {
  if (!value) return "Unknown time";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "Unknown time";
  const diff = Date.now() - timestamp;
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

export function formatExactTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "Unknown time";
}
