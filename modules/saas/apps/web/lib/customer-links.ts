/** Words and rules for the people-across-channels view (Phase 5B). Pure, unit tested. */
import type { LinkPlatform, LinkState } from "./api";

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
