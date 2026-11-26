/**
 * Old Many dashboard URLs and where they go now (decision P6, Phase 4B).
 *
 * A path whose new page exists redirects there. Pages built in 4C and 4D redirect to
 * their new place; `/moved` remains for any old address added later. The query string is passed through by Next.js.
 * `/privacy`, `/terms` and `/login` are the same in both apps and need no entry.
 */

export interface OldUrl {
  source: string;
  destination: string;
}

export const OLD_URL_REDIRECTS: readonly OldUrl[] = [
  { source: "/overview", destination: "/platform/many" },
  // `/accounts` is a real page now: it sends each person to the right place by session.
  {
    source: "/campaigns/new",
    destination: "/platform/instagram/campaigns/new",
  },
  {
    source: "/campaigns/:id/stats",
    destination: "/platform/instagram/campaigns/:id/stats",
  },
  {
    source: "/campaigns/:id",
    destination: "/platform/instagram/campaigns/:id",
  },
  { source: "/campaigns", destination: "/platform/instagram/campaigns" },
  {
    source: "/conversations",
    destination: "/platform/instagram/conversations",
  },
  { source: "/leads", destination: "/platform/leads" },
  { source: "/logs", destination: "/platform/logs" },
  { source: "/messages", destination: "/platform/messages" },
  // Facebook and WhatsApp pages now live inside an organization, which the old address does
  // not name: the workspace list (or the person's only organization) is the way in.
  { source: "/facebook-campaigns", destination: "/app" },
  { source: "/whatsapp", destination: "/app" },
  { source: "/whatsapp/:path*", destination: "/app" },
];
