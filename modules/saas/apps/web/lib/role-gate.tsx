"use client";

import type { ReactNode } from "react";

import { orgRoleSatisfies, type OrgRole } from "./org-role";
import { PageState } from "./page-state";
import { Loading } from "./ui";
import { useOrgRole } from "./use-org-role";

/**
 * Show `children` only to people whose organization role reaches `minimum` (Phase 4C).
 * Others see the forbidden state, not a toast. This is a courtesy: the proxy and Many check
 * the role again on every call, so a hidden page that is opened by URL still gets a 403.
 * Platform staff count as Admin here, which is the role their Many membership carries.
 */
export function RoleGate({
  tenantId,
  minimum,
  children,
}: {
  tenantId: string;
  minimum: OrgRole;
  children: ReactNode;
}) {
  const { role, loading } = useOrgRole(tenantId);
  if (loading) return <Loading />;
  if (!orgRoleSatisfies(role, minimum)) {
    return (
      <PageState
        status={{ kind: "failed", failure: "forbidden" }}
        homeHref={`/app/${tenantId}`}
      >
        {null}
      </PageState>
    );
  }
  return <>{children}</>;
}
