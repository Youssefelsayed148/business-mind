import type { ManyConversation } from "./types";

export const STATUS_FILTERS = [
  "all",
  "bot_active",
  "handed_off",
  "closed",
] as const;
export const PLATFORM_FILTERS = [
  "all",
  "instagram",
  "whatsapp",
  "facebook",
] as const;

export function filterConversations(
  rows: ManyConversation[],
  status: string,
  platform: string,
): ManyConversation[] {
  return rows
    .filter((c) => status === "all" || c.status === status)
    .filter((c) => platform === "all" || c.platform === platform);
}

export type ConversationControl =
  /** Delegated to the shared inbox: Many shows no Take Over or Resume bot. */
  | { kind: "shared_inbox"; href: string | null }
  | { kind: "take_over" }
  | { kind: "resume_bot" };

/**
 * What a staff member may do with a conversation. A delegated row (`managed_by_saas`) only
 * points to the shared inbox, and only when the row names the organization.
 */
export function conversationControl(
  row: Pick<ManyConversation, "managed_by_saas" | "tenant_id" | "status">,
): ConversationControl {
  if (row.managed_by_saas) {
    const tenant =
      typeof row.tenant_id === "string" && row.tenant_id.trim()
        ? row.tenant_id.trim()
        : null;
    return {
      kind: "shared_inbox",
      href: tenant ? `/app/${encodeURIComponent(tenant)}/inbox` : null,
    };
  }
  return row.status === "bot_active"
    ? { kind: "take_over" }
    : { kind: "resume_bot" };
}
