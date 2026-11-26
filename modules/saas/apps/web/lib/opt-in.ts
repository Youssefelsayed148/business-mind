/** Helpers for the public WhatsApp opt-in page (Phase 4C). */

/**
 * The phone number the API accepts: a leading + and 6 to 20 digits. Spaces, dashes, dots and
 * brackets people type are removed; anything else returns null (the page then asks again).
 */
export function cleanOptInPhone(input: string): string | null {
  const trimmed = input.trim();
  if (!trimmed.startsWith("+")) return null;
  const compact = `+${trimmed.slice(1).replace(/[\s().-]/g, "")}`;
  return /^\+[0-9]{6,20}$/.test(compact) ? compact : null;
}

/** Only a WhatsApp click-to-chat link is ever opened: the address comes from another service. */
export function safeChatUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "wa.me"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}
