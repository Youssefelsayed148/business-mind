"use client";

import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { RoleGate } from "@/lib/role-gate";

import { WhatsappShell } from "./whatsapp-shell";

/**
 * Every WhatsApp outreach page needs an Admin or Owner, reads included (Many checks the same
 * on every call). Anyone else sees the forbidden state and no Many call is made.
 */
export default function WhatsappLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ tenant: string }>();
  return (
    <RoleGate tenantId={params.tenant} minimum="admin">
      <WhatsappShell tenantId={params.tenant}>{children}</WhatsappShell>
    </RoleGate>
  );
}
