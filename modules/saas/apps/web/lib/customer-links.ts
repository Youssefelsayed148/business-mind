/** Words and rules for the people-across-channels view (Phase 5B). Pure, unit tested. */
import type { ErasureState, LinkPlatform, LinkState } from "./api";

export const PLATFORM_LABEL: Record<LinkPlatform, string> = {
  whatsapp: "WhatsApp",
  instagram: "Instagram",
  facebook: "Facebook",
};

export const STATE_LABEL: Record<LinkState, string> = {
  linked: "Linked",
  many_only: "Outreach only",
  saas_only: "Chat only",
  conflict: "Needs review",
};

export const STATE_HELP: Record<LinkState, string> = {
  linked: "Known to the chat inbox and to the outreach tools.",
  many_only:
    "Known to the outreach tools only. No contact exists in the chat inbox yet.",
  saas_only: "A chat contact with no outreach record on this channel.",
  conflict:
    "More than one contact claims this person. A staff member must merge them.",
};

export function stateHelp(value: string): string {
  return (STATE_HELP as Record<string, string>)[value] ?? "";
}

export function platformLabel(value: string): string {
  return (PLATFORM_LABEL as Record<string, string>)[value] ?? value;
}

export function stateLabel(value: string): string {
  return (STATE_LABEL as Record<string, string>)[value] ?? value;
}

export function stateTone(value: string): "success" | "warning" | "neutral" {
  if (value === "linked") return "success";
  if (value === "conflict") return "warning";
  return "neutral";
}

/** The name to show: the contact's, else the username Many holds, else a plain fallback. */
export function personName(link: {
  contact_name: string | null;
  display_name: string | null;
}): string {
  return link.contact_name?.trim() || link.display_name?.trim() || "Unnamed";
}

export const PAGE_SIZE = 50;

/** The next offset, or null on the last page. */
export function nextOffset(
  offset: number,
  total: number,
  size = PAGE_SIZE,
): number | null {
  return offset + size < total ? offset + size : null;
}

export function previousOffset(
  offset: number,
  size = PAGE_SIZE,
): number | null {
  return offset > 0 ? Math.max(0, offset - size) : null;
}

export const ERASURE_LABEL: Record<ErasureState, string> = {
  requested: "Started",
  saas_erased: "Erased here, waiting for the outreach service",
  complete: "Complete",
  needs_action: "Needs attention",
};

export function erasureLabel(value: string): string {
  return (ERASURE_LABEL as Record<string, string>)[value] ?? value;
}

export function erasureTone(value: string): "success" | "warning" | "neutral" {
  if (value === "complete") return "success";
  if (value === "needs_action") return "warning";
  return "neutral";
}

/** Only a case that stopped, or one still waiting, can be tried again. */
export function canRetry(value: string): boolean {
  return (
    value === "needs_action" || value === "saas_erased" || value === "requested"
  );
}

export const ERASE_WARNING =
  "This erases the person's chat contact, conversations and messages here, and asks the outreach service to erase them too. It cannot be undone. Their other channels stay until you erase each one.";

export const RANGE_OPTIONS = [7, 30, 90] as const;

/** "0.012 USD" style; only when some calls had a measured cost. */
export function costText(callsWithCost: number, costUsd: number): string {
  if (callsWithCost <= 0) return "Not measured";
  return `${costUsd.toFixed(costUsd < 1 ? 3 : 2)} USD (${callsWithCost} measured call${callsWithCost === 1 ? "" : "s"})`;
}

export function sourceLabel(value: string): string {
  return value === "many" ? "Outreach service" : "Chat inbox";
}

export function levelTone(value: string): "danger" | "warning" | "neutral" {
  if (value === "error" || value === "danger") return "danger";
  if (value === "warning") return "warning";
  return "neutral";
}
