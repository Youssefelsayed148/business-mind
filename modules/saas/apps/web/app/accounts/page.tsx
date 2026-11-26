"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import {
  accountsLoginTarget,
  accountsReturnTarget,
} from "@/lib/accounts-return";
import { useSession } from "@/lib/session";
import { Loading, Notice } from "@/lib/ui";

/**
 * Kept for old Instagram and Meta redirects (`/accounts?connected=true`). It reads the
 * session and sends the person on, keeping the whole query string; it shows nothing itself.
 */
export default function AccountsReturnPage() {
  const router = useRouter();
  const { me, loading, error } = useSession();

  useEffect(() => {
    if (loading) return;
    const search = window.location.search;
    if (!me) {
      // Signed out: sign in, then come back here and be sent on.
      if (!error) router.replace(accountsLoginTarget(search));
      return;
    }
    router.replace(
      accountsReturnTarget({
        isStaff: me.is_platform_staff,
        tenantIds: me.memberships.map((membership) => membership.tenant_id),
        search,
      }),
    );
  }, [loading, me, error, router]);

  if (!loading && !me && error) {
    return (
      <main className="auth-page">
        <Notice message={error} tone="error" />
      </main>
    );
  }
  return (
    <main className="auth-page">
      <Loading label="Taking you to your channels..." />
    </main>
  );
}
