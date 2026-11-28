"use client";

import { useEffect, useState } from "react";

import * as api from "./api";

/** True once the people-across-channels view answered for this organization (flag on, role ok). */
export function useCustomerLinksAvailable(
  tenantId: string,
  allowed: boolean,
): boolean {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    if (!allowed) return;
    let cancelled = false;
    api
      .customerLinks(tenantId, { limit: 1 })
      .then(() => !cancelled && setAvailable(true))
      .catch(() => !cancelled && setAvailable(false));
    return () => {
      cancelled = true;
    };
  }, [tenantId, allowed]);
  return allowed && available;
}

/** True once the combined audit view answers (flag on, platform staff). */
export function useAuditViewAvailable(): boolean {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api
      .combinedAudit({ source: "saas", limit: 1 })
      .then(() => !cancelled && setAvailable(true))
      .catch(() => !cancelled && setAvailable(false));
    return () => {
      cancelled = true;
    };
  }, []);
  return available;
}
