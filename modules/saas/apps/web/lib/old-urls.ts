/**
 * Old Many dashboard URLs and where they go now (decision P6, Phase 4B).
 *
 * A path whose new page exists redirects there. A path whose page comes in 4C or 4D goes to
 * `/moved`, which says so instead of showing a 404. When a page ships, change its line
 * here and nothing else. The query string is passed through by Next.js.
 * `/privacy`, `/terms` and `/login` are the same in both apps and need no entry.
 */

export interface OldUrl {
  source: string;
  destination: string;
}

const moved = (from: string): string =>
  `/moved?from=${encodeURIComponent(from)}`;

export const OLD_URL_REDIRECTS: readonly OldUrl[] = [
  { source: "/overview", destination: "/platform/many" },
  { source: "/accounts", destination: moved("/accounts") },
  { source: "/campaigns", destination: moved("/campaigns") },
  { source: "/campaigns/:path*", destination: moved("/campaigns") },
  { source: "/conversations", destination: moved("/conversations") },
  { source: "/facebook-campaigns", destination: moved("/facebook-campaigns") },
  { source: "/leads", destination: moved("/leads") },
  { source: "/logs", destination: moved("/logs") },
  { source: "/messages", destination: moved("/messages") },
  { source: "/whatsapp", destination: moved("/whatsapp") },
  { source: "/whatsapp/:path*", destination: moved("/whatsapp") },
];
