/**
 * Organization roles for the shell (Phase 4B, gap 9).
 *
 * `/auth/me` exposes only the stored roles admin, editor and viewer. The real role
 * (Owner, Admin, Manager, Agent, Viewer) comes from `GET /tenants/{id}/summary`. With
 * identity v2 off that endpoint answers 404, and the shell falls back to the stored role
 * through the same mapping the API uses. The API check stays the real gate; this only
 * decides what to show.
 */

export type OrgRole = "owner" | "admin" | "manager" | "agent" | "viewer";
export type StoredRole = "admin" | "editor" | "viewer";

const LEVEL: Record<OrgRole, number> = {
  viewer: 1,
  agent: 2,
  manager: 3,
  admin: 4,
  owner: 5,
};

/** Same table as the API (`LEGACY_TO_ORG_ROLE`): never escalates. */
const LEGACY: Record<StoredRole, OrgRole> = {
  viewer: "viewer",
  editor: "agent",
  admin: "admin",
};

export function orgRoleFromStored(role: StoredRole | null): OrgRole | null {
  return role ? LEGACY[role] : null;
}

/**
 * The role in a summary answer. Platform staff acting in an organization are shown as
 * Admin: that is the role their Many membership carries (P2).
 */
export function orgRoleFromSummary(value: unknown): OrgRole | null {
  if (value === "platform_staff") return "admin";
  if (typeof value === "string" && Object.hasOwn(LEVEL, value)) {
    return value as OrgRole;
  }
  return null;
}

export function orgRoleSatisfies(
  current: OrgRole | null,
  minimum: OrgRole,
): boolean {
  return current !== null && LEVEL[current] >= LEVEL[minimum];
}

export const ORG_ROLE_LABEL: Record<OrgRole, string> = {
  owner: "Owner",
  admin: "Admin",
  manager: "Manager",
  agent: "Agent",
  viewer: "Viewer",
};
