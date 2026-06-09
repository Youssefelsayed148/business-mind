"use client";

import { useEffect, useState } from "react";
import { Link2 } from "lucide-react";
import { MockConnect } from "@/components/accounts/MockConnect";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { LiveStatusDot } from "@/components/ui/LiveStatusDot";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { TableWrap, tableClass, tdClass, thClass, theadRowClass, trClass } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { useCan } from "@/lib/permissions";
import { useToast } from "@/components/ToastProvider";
import type { InstagramAccount } from "@/lib/types";

function expiryStatus(account: InstagramAccount) {
  if (account.status === "disconnected") return "Disconnected";
  if (!account.expires_at) return "Connected";
  const expiry = new Date(account.expires_at).getTime();
  const days = (expiry - Date.now()) / 86400000;
  if (days < 0) return "Reconnect Required";
  if (days <= 7) return "Expiring Soon";
  return "Connected";
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<InstagramAccount[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const canManageAccounts = useCan("manage_accounts");
  const canDisconnectAccounts = useCan("disconnect_accounts");
  const toast = useToast();
  const [connecting, setConnecting] = useState(false);

  async function connectInstagram() {
    setConnecting(true);
    try {
      const { oauth_url } = await api.get<{ oauth_url: string }>("/meta/connect/start");
      window.location.href = oauth_url;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start Instagram connection");
      setConnecting(false);
    }
  }

  async function load() {
    setLoading(true);
    api.get<InstagramAccount[]>("/instagram/accounts")
      .then(setAccounts)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load accounts"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("connected");
    const errorParam = params.get("error");
    if (connected === "true") {
      toast.success("Instagram account connected successfully");
      window.history.replaceState({}, "", "/accounts");
      load();
    } else if (errorParam === "oauth_failed") {
      toast.error("Failed to connect Instagram account. Please try again.");
      window.history.replaceState({}, "", "/accounts");
    }
  }, []);

  async function disconnect(id: string) {
    try {
      await api.delete(`/instagram/accounts/${id}`);
      toast.success("Account disconnected.");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to disconnect account");
    }
  }

  async function reconnect(id: string) {
    try {
      await api.post(`/instagram/accounts/${id}/reconnect`);
      toast.success("Account reconnected.");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to reconnect account");
    }
  }

  return (
    <div className="grid gap-6">
      <PageHeader title="Accounts" description="Manage connected Instagram accounts. Use Connect Instagram to link a new Business account via OAuth.">
        {canManageAccounts ? (
          <Button type="button" className="gap-2" onClick={connectInstagram} disabled={connecting}>
            <Link2 className="h-4 w-4" aria-hidden="true" />
            {connecting ? "Connecting..." : "Connect Instagram"}
          </Button>
        ) : null}
      </PageHeader>
      {canManageAccounts && process.env.NEXT_PUBLIC_APP_ENV !== "production" ? <MockConnect onConnected={load} /> : null}
      <Panel>
        <div className="mb-4">
          <h2 className="text-lg font-bold text-ink">Connected accounts</h2>
          <p className="mt-1 text-sm text-muted">Review account status, token expiry, and lifecycle actions.</p>
        </div>
        <DataState loading={loading} error={error} />
        {loading ? <TableSkeleton rows={4} columns={6} /> : null}
        {!loading && !error && accounts.length === 0 ? <EmptyState title="No accounts connected" message="Use the mock connector above in development to add an Instagram account." /> : null}
        {accounts.length > 0 ? (
        <TableWrap>
          <table className={`${tableClass} min-w-[760px]`}>
            <thead>
              <tr className={theadRowClass}>
                <th className={thClass}>Username</th>
                <th className={thClass}>Account type</th>
                <th className={thClass}>Status</th>
                <th className={thClass}>Token expiry</th>
                <th className={thClass}>Last active</th>
                <th className={thClass}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => {
                const isConnected = account.status === "connected" || !account.status;
                const isDisconnected = account.status === "disconnected";
                return (
                  <tr key={account.id} className={trClass}>
                    <td className={`${tdClass} font-semibold text-ink`}>
                      <span className="inline-flex items-center gap-2">
                        <Avatar label={account.username || account.ig_user_id} size="sm" />
                        {account.username || account.ig_user_id}
                      </span>
                    </td>
                    <td className={tdClass}>{account.account_type || "Business"}</td>
                    <td className={tdClass}>
                      <span className="inline-flex items-center gap-2">
                        <LiveStatusDot tone={isConnected ? "success" : "warning"} />
                        <Badge value={expiryStatus(account).toLowerCase().replaceAll(" ", "_")} />
                      </span>
                    </td>
                    <td className={tdClass}>{account.expires_at ? new Date(account.expires_at).toLocaleString() : "Not available"}</td>
                    <td className={tdClass}>{account.updated_at || account.created_at ? new Date(account.updated_at || account.created_at || "").toLocaleString() : "Not available"}</td>
                    <td className={`${tdClass} flex gap-2`}>
                      {canManageAccounts ? <Button type="button" variant="secondary" disabled={!isDisconnected} onClick={() => reconnect(account.id)}>Reconnect</Button> : null}
                      {canDisconnectAccounts ? <Button type="button" variant="danger" disabled={!isConnected} onClick={() => disconnect(account.id)}>Disconnect</Button> : null}
                      {!canManageAccounts && !canDisconnectAccounts ? <span className="text-sm text-muted">Read only</span> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
        ) : null}
      </Panel>
    </div>
  );
}
