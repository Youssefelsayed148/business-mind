"use client";

import { useEffect, useState } from "react";

import { manyRequest } from "@/lib/many";

import type { ManyCampaign, ManyInstagramAccount } from "./types";

/**
 * A best-effort list from Many for a filter or a name lookup (campaigns, Instagram accounts).
 * Like the old pages, a failure leaves the list empty instead of failing the page.
 */
export function useStaffList<T>(path: string): T[] {
  const [items, setItems] = useState<T[]>([]);
  useEffect(() => {
    let cancelled = false;
    manyRequest<T[]>({ kind: "staff" }, "GET", path).then(
      (data) => {
        if (!cancelled) setItems(Array.isArray(data) ? data : []);
      },
      () => {
        if (!cancelled) setItems([]);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [path]);
  return items;
}

export const useStaffCampaigns = () => useStaffList<ManyCampaign>("campaigns");
export const useStaffInstagramAccounts = () =>
  useStaffList<ManyInstagramAccount>("instagram/accounts");
