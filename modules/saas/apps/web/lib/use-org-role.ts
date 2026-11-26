"use client";

import { useEffect, useState } from "react";

import { tenantSummary } from "./api";
import {
  orgRoleFromStored,
  orgRoleFromSummary,
  type OrgRole,
} from "./org-role";
import { useSession } from "./session";

/**
 * The person's real organization role (Owner, Admin, Manager, Agent, Viewer).
 *
 * Asks `GET /tenants/{id}/summary`; if it is not available (identity v2 off, or any
 * failure) it uses the stored role through the API's own mapping. Display only: the API
 * decides what is allowed.
 */
export function useOrgRole(tenantId: string | undefined): {
  role: OrgRole | null;
  loading: boolean;
} {
  const { roleIn } = useSession();
  const [answer, setAnswer] = useState<{
    tenantId: string;
    role: OrgRole | null;
  } | null>(null);
  useEffect(() => {
    if (!tenantId) return;
    let cancelled = false;
    tenantSummary(tenantId)
      .then((summary) => {
        if (!cancelled)
          setAnswer({ tenantId, role: orgRoleFromSummary(summary.role) });
      })
      .catch(() => {
        if (!cancelled) setAnswer({ tenantId, role: null });
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);
  if (!tenantId) return { role: null, loading: false };
  if (!answer || answer.tenantId !== tenantId) {
    return { role: null, loading: true };
  }
  const stored = roleIn(tenantId);
  return {
    role: answer.role ?? orgRoleFromStored(stored),
    loading: false,
  };
}
