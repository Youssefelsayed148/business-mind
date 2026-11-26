/** Pure helpers for the identity screens (Phase 4E). */

import type { OrgRoleName } from "./api";
import { ORG_ROLE_LABEL, type OrgRole } from "./org-role";

/** Roles a person may offer when inviting, by their own role (the API checks again). */
export function invitableRoles(actor: OrgRole | null): OrgRoleName[] {
  if (actor === "owner") return ["admin", "manager", "agent", "viewer"];
  if (actor === "admin") return ["manager", "agent", "viewer"];
  return [];
}

export function roleLabel(role: string): string {
  return Object.hasOwn(ORG_ROLE_LABEL, role)
    ? ORG_ROLE_LABEL[role as OrgRole]
    : role;
}

/** Same minimum as the API (`PASSWORD_MIN_LENGTH`); the API still decides. */
export const PASSWORD_MIN = 8;

export function passwordProblem(
  password: string,
  confirm: string,
): string | null {
  if (password.length < PASSWORD_MIN)
    return `Use at least ${PASSWORD_MIN} characters.`;
  if (password !== confirm) return "The two passwords do not match.";
  return null;
}

/** A TOTP or recovery code as people type it: no spaces. Returns null when too short. */
export function cleanCode(input: string): string | null {
  const code = input.replace(/\s+/g, "");
  return code.length >= 6 && code.length <= 32 ? code : null;
}

/** "Chrome on Windows"-style text from a user agent, or a plain fallback. */
export function deviceLabel(userAgent: string | null): string {
  if (!userAgent) return "Unknown device";
  const browser = /Edg\//.test(userAgent)
    ? "Edge"
    : /Chrome\//.test(userAgent)
      ? "Chrome"
      : /Firefox\//.test(userAgent)
        ? "Firefox"
        : /Safari\//.test(userAgent)
          ? "Safari"
          : "Browser";
  const system = /Windows/.test(userAgent)
    ? "Windows"
    : /iPhone|iPad|iOS/.test(userAgent)
      ? "iOS"
      : /Android/.test(userAgent)
        ? "Android"
        : /Mac OS X/.test(userAgent)
          ? "macOS"
          : /Linux/.test(userAgent)
            ? "Linux"
            : "";
  return system ? `${browser} on ${system}` : browser;
}

/** The setup address of an invitation link is shown whole only on this origin. */
export function inviteUrl(
  linkPath: string | null,
  origin: string,
): string | null {
  if (!linkPath || !linkPath.startsWith("/") || linkPath.startsWith("//"))
    return null;
  return `${origin}${linkPath}`;
}
