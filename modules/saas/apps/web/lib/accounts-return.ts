/**
 * Where the old `/accounts` address leads (Phase 4C).
 *
 * Meta and Instagram redirects that were registered with the old dashboard still arrive at
 * `/accounts?connected=true` (or `?error=...`). The whole query string is kept so the
 * destination page can read it. Pure: the page supplies the session facts.
 *
 * - platform staff: the staff Instagram accounts page;
 * - exactly one organization: that organization's channels page;
 * - none or several: the organization list, where the person chooses.
 */
export function accountsReturnTarget({
  isStaff,
  tenantIds,
  search,
}: {
  isStaff: boolean;
  tenantIds: readonly string[];
  search: string;
}): string {
  const query =
    search && search !== "?"
      ? search.startsWith("?")
        ? search
        : `?${search}`
      : "";
  if (isStaff) return `/platform/instagram/accounts${query}`;
  const unique = [...new Set(tenantIds)];
  if (unique.length === 1) {
    return `/app/${encodeURIComponent(unique[0])}/channels${query}`;
  }
  return `/app${query}`;
}

/** Pure: the sign-in address that brings the person back to `/accounts` with its query. */
export function accountsLoginTarget(search: string): string {
  const query =
    search && search !== "?"
      ? search.startsWith("?")
        ? search
        : `?${search}`
      : "";
  return `/login?next=${encodeURIComponent(`/accounts${query}`)}`;
}
