/** Where the organization switcher goes (docs/PHASE-4-PLAN.md 12.3, Phase 4B). */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Keep the current page when the person changes organization: the path after the
 * organization, cut before the first id, so `/app/A/settings/members` becomes
 * `/app/B/settings/members` and `/app/A/bots/<bot>/settings` becomes `/app/B/bots`.
 * The destination decides whether this person may open it (the layout and the API).
 */
export function switchTarget(options: {
  pathname: string;
  currentTenantId: string | undefined;
  nextTenantId: string;
  isStaff: boolean;
  archived: boolean;
}): string {
  const { pathname, currentTenantId, nextTenantId, isStaff, archived } =
    options;
  if (archived && isStaff) return `/platform/clients/${nextTenantId}`;
  const base = `/app/${nextTenantId}`;
  const fallback = isStaff ? `${base}/bots` : base;
  if (!currentTenantId) return fallback;
  const prefix = `/app/${currentTenantId}/`;
  if (!pathname.startsWith(prefix)) return fallback;
  const kept: string[] = [];
  for (const part of pathname.slice(prefix.length).split("/")) {
    if (!part || UUID.test(part)) break;
    kept.push(part);
  }
  return kept.length ? `${base}/${kept.join("/")}` : fallback;
}
