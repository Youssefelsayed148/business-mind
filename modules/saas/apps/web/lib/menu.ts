/**
 * The menu tree from docs/PHASE-4-PLAN.md section 12.2, as data (Phase 4B).
 *
 * `shipped` is false until the page exists (4C and 4D), so the sidebar never links to a
 * page that is not there. A hidden item is a courtesy: the API still checks every call.
 */
import { orgRoleSatisfies, type OrgRole } from "./org-role";

export interface MenuEntry {
  group:
    "Many (staff)" | "Instagram (staff)" | "Channels" | "WhatsApp" | "Facebook";
  label: string;
  /** Path below `/app/[tenant]` (client) or an absolute `/platform/...` path (staff). */
  path: string;
  staffOnly?: boolean;
  /** Smallest organization role that sees it (client items only). */
  minimumRole?: OrgRole;
  shipped: boolean;
}

export const MENU: readonly MenuEntry[] = [
  // Staff, under /platform.
  {
    group: "Many (staff)",
    label: "Many overview",
    path: "/platform/many",
    staffOnly: true,
    shipped: true,
  },
  {
    group: "Many (staff)",
    label: "Leads",
    path: "/platform/leads",
    staffOnly: true,
    shipped: false,
  },
  {
    group: "Many (staff)",
    label: "Messages",
    path: "/platform/messages",
    staffOnly: true,
    shipped: false,
  },
  {
    group: "Many (staff)",
    label: "Logs",
    path: "/platform/logs",
    staffOnly: true,
    shipped: false,
  },
  {
    group: "Instagram (staff)",
    label: "Instagram accounts",
    path: "/platform/instagram/accounts",
    staffOnly: true,
    shipped: false,
  },
  {
    group: "Instagram (staff)",
    label: "Instagram campaigns",
    path: "/platform/instagram/campaigns",
    staffOnly: true,
    shipped: false,
  },
  {
    group: "Instagram (staff)",
    label: "Instagram conversations",
    path: "/platform/instagram/conversations",
    staffOnly: true,
    shipped: false,
  },
  // Client, under /app/[tenant].
  {
    group: "Channels",
    label: "Accounts",
    path: "/channels",
    minimumRole: "viewer",
    shipped: false,
  },
  {
    group: "WhatsApp",
    label: "WhatsApp contacts",
    path: "/whatsapp/contacts",
    minimumRole: "admin",
    shipped: false,
  },
  {
    group: "WhatsApp",
    label: "WhatsApp templates",
    path: "/whatsapp/templates",
    minimumRole: "admin",
    shipped: false,
  },
  {
    group: "WhatsApp",
    label: "WhatsApp campaigns",
    path: "/whatsapp/campaigns",
    minimumRole: "admin",
    shipped: false,
  },
  {
    group: "WhatsApp",
    label: "WhatsApp health",
    path: "/whatsapp/health",
    minimumRole: "admin",
    shipped: false,
  },
  {
    group: "Facebook",
    label: "Facebook campaigns",
    path: "/facebook/campaigns",
    minimumRole: "viewer",
    shipped: false,
  },
];

/** Entries this person sees. `tenantId` is needed for client entries. */
export function visibleMenu(options: {
  isStaff: boolean;
  role: OrgRole | null;
  tenantId?: string;
}): { entry: MenuEntry; href: string }[] {
  const out: { entry: MenuEntry; href: string }[] = [];
  for (const entry of MENU) {
    if (!entry.shipped) continue;
    if (entry.staffOnly) {
      if (options.isStaff) out.push({ entry, href: entry.path });
      continue;
    }
    if (!options.tenantId) continue;
    if (
      entry.minimumRole &&
      !orgRoleSatisfies(options.role, entry.minimumRole)
    ) {
      continue;
    }
    out.push({ entry, href: `/app/${options.tenantId}${entry.path}` });
  }
  return out;
}
