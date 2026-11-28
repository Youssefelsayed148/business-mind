import type { ManyMessage } from "./types";

/**
 * A cold-DM AI message has no originating campaign. Many serializes the null campaign id as
 * the string "None", so both null and "None" mean "no campaign".
 */
export function hasCampaign(campaignId?: string | null): boolean {
  return !!campaignId && campaignId !== "None";
}

export function campaignLabel(
  campaignId: string | null | undefined,
  names: Record<string, string>,
): string {
  if (!hasCampaign(campaignId)) return "Cold DM";
  return names[campaignId as string] || (campaignId as string);
}

export function messageTypeLabel(value?: string | null): string {
  if (value === "follow_prompt") return "Follow prompt";
  if (value === "retry") return "Retry";
  return "Final delivery";
}

export function retriesLabel(count: number): string {
  return `${count} ${count === 1 ? "retry" : "retries"}`;
}

/** Only a failed message that Many marks retryable can be retried. */
export function canRetry(message: ManyMessage): boolean {
  return message.status === "failed" && message.retryable;
}
