"use client";

import { useEffect, useState } from "react";
import { Bot, Link2, Trash2 } from "lucide-react";
import { MockConnect } from "@/components/accounts/MockConnect";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Field, Select, TextArea } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { LiveStatusDot } from "@/components/ui/LiveStatusDot";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { TableWrap, tableClass, tdClass, thClass, theadRowClass, trClass } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { useCan } from "@/lib/permissions";
import { useToast } from "@/components/ToastProvider";
import type { AISettingsPayload, InstagramAccount } from "@/lib/types";

function AISettingsPanel({
  account,
  canManage,
  onSaved,
}: {
  account: InstagramAccount;
  canManage: boolean;
  onSaved: (updated: InstagramAccount) => void;
}) {
  const [form, setForm] = useState<AISettingsPayload>({
    business_vertical: (account.business_vertical as AISettingsPayload["business_vertical"]) || "general",
    ai_enabled: account.ai_enabled || false,
    ai_cold_dm_enabled: account.ai_cold_dm_enabled || false,
    ai_business_profile: account.ai_business_profile || "",
    ai_tone_instructions: account.ai_tone_instructions || "",
    ai_daily_message_cap: account.ai_daily_message_cap ?? 100,
  });
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  async function save() {
    setSaving(true);
    try {
      const updated = await api.patch<InstagramAccount>(`/instagram/accounts/${account.id}/ai-settings`, form);
      toast.success("AI settings saved.");
      onSaved(updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save AI settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid gap-4 rounded-lg border border-line/70 bg-slate-50/60 p-4">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-sm font-bold text-ink">AI conversation assistant</h4>
          <p className="text-xs text-muted">
            Shared across all campaigns on this account. Used only once a lead replies inside a DM thread.
          </p>
        </div>
        <label className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
          <input
            type="checkbox"
            checked={form.ai_enabled}
            disabled={!canManage}
            onChange={(e) => setForm((f) => ({ ...f, ai_enabled: e.target.checked }))}
            className="h-4 w-4 rounded border-line accent-accent"
          />
          Enabled
        </label>
      </div>

      <label className="flex items-start gap-2 rounded-lg border border-line/70 bg-white p-3 text-sm text-ink">
        <input
          type="checkbox"
          checked={form.ai_cold_dm_enabled || false}
          disabled={!canManage || !form.ai_enabled}
          onChange={(e) => setForm((f) => ({ ...f, ai_cold_dm_enabled: e.target.checked }))}
          className="mt-0.5 h-4 w-4 rounded border-line accent-accent"
        />
        <span>
          <span className="font-semibold">Also let AI answer unsolicited DMs</span>
          <span className="mt-0.5 block text-xs text-muted">
            Separate opt-in. When on, the AI also replies to people who message this account
            directly without ever going through a campaign. Leaving it off changes nothing about
            campaign conversations — those still require this main toggle only.
          </span>
        </span>
      </label>

      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          label="Business vertical"
          hint="Applies non-overridable safety rules (e.g. clinics never give medical advice)."
          value={form.business_vertical}
          disabled={!canManage}
          onChange={(e) => setForm((f) => ({ ...f, business_vertical: e.target.value as AISettingsPayload["business_vertical"] }))}
        >
          <option value="general">General</option>
          <option value="restaurant">Restaurant</option>
          <option value="real_estate">Real estate</option>
          <option value="clinical">Clinical</option>
        </Select>
        <Field
          label="Daily message cap"
          type="number"
          min={0}
          max={5000}
          hint={`Shared budget across all campaigns on this account. Sent today: ${account.ai_messages_sent_today ?? 0}.`}
          value={form.ai_daily_message_cap}
          disabled={!canManage}
          onChange={(e) => setForm((f) => ({ ...f, ai_daily_message_cap: Number(e.target.value) }))}
        />
      </div>

      <TextArea
        label="Business profile"
        hint="Facts the AI should know: what the business offers, hours, delivery area, contact for humans. Be specific — a sparse profile leads to vague or unsafe answers."
        rows={5}
        value={form.ai_business_profile || ""}
        disabled={!canManage}
        onChange={(e) => setForm((f) => ({ ...f, ai_business_profile: e.target.value }))}
      />

      <TextArea
        label="Tone / style (optional)"
        hint="e.g. 'Friendly and casual, use emojis sparingly.'"
        rows={2}
        value={form.ai_tone_instructions || ""}
        disabled={!canManage}
        onChange={(e) => setForm((f) => ({ ...f, ai_tone_instructions: e.target.value }))}
      />

      {canManage ? (
        <div className="flex justify-end">
          <Button type="button" disabled={saving} onClick={save}>
            {saving ? "Saving..." : "Save AI settings"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

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
  const [connecting, setConnecting] = useState(false);
  const [reconnectingId, setReconnectingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const canManageAccounts = useCan("manage_accounts");
  const canDisconnectAccounts = useCan("disconnect_accounts");
  const canDeleteAccounts = useCan("delete_accounts");
  const toast = useToast();

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
    const reconnected = params.get("reconnected");
    const errorParam = params.get("error");

    if (connected === "true") {
      toast.success("Instagram account connected successfully");
      window.history.replaceState({}, "", "/accounts");
      load();
    } else if (reconnected === "true") {
      toast.success("Instagram account reconnected successfully");
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

  /**
   * Reconnect via real OAuth — backend returns an oauth_url, we redirect there.
   * The callback updates the existing account row in place.
   */
  async function reconnect(id: string) {
    setReconnectingId(id);
    try {
      const { oauth_url } = await api.post<{ oauth_url: string }>(
        `/instagram/accounts/${id}/reconnect`
      );
      window.location.href = oauth_url;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start reconnect");
      setReconnectingId(null);
    }
  }

  async function hardDelete(id: string) {
    setDeletingId(id);
    setConfirmDeleteId(null);
    try {
      await api.delete(`/instagram/accounts/${id}/hard`);
      toast.success("Account permanently deleted.");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete account");
    } finally {
      setDeletingId(null);
    }
  }

  const confirmTarget = accounts.find((a) => a.id === confirmDeleteId);

  return (
    <div className="grid gap-6">
      <PageHeader
        title="Accounts"
        description="Manage connected Instagram accounts. Use Connect Instagram to link a new Business account via OAuth."
      >
        {canManageAccounts ? (
          <Button type="button" className="gap-2" onClick={connectInstagram} disabled={connecting}>
            <Link2 className="h-4 w-4" aria-hidden="true" />
            {connecting ? "Connecting..." : "Connect Instagram"}
          </Button>
        ) : null}
      </PageHeader>

      {canManageAccounts && process.env.NEXT_PUBLIC_APP_ENV !== "production" ? (
        <MockConnect onConnected={load} />
      ) : null}

      {/* Confirm delete dialog */}
      {confirmDeleteId && confirmTarget ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <Panel className="max-w-md w-full mx-4">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-100">
                <Trash2 className="h-5 w-5 text-red-600" />
              </div>
              <div>
                <h3 className="text-base font-bold text-ink">Delete account permanently?</h3>
                <p className="mt-1 text-sm text-muted">
                  This will permanently delete{" "}
                  <span className="font-semibold text-ink">
                    @{confirmTarget.username || confirmTarget.ig_user_id}
                  </span>{" "}
                  and all associated campaigns, messages, and tokens. This action cannot be undone.
                </p>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setConfirmDeleteId(null)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="danger"
                disabled={deletingId === confirmDeleteId}
                onClick={() => hardDelete(confirmDeleteId)}
              >
                {deletingId === confirmDeleteId ? "Deleting..." : "Delete permanently"}
              </Button>
            </div>
          </Panel>
        </div>
      ) : null}

      <Panel>
        <div className="mb-4">
          <h2 className="text-lg font-bold text-ink">Connected accounts</h2>
          <p className="mt-1 text-sm text-muted">
            Review account status, token expiry, and lifecycle actions.
          </p>
        </div>
        <DataState loading={loading} error={error} />
        {loading ? <TableSkeleton rows={4} columns={6} /> : null}
        {!loading && !error && accounts.length === 0 ? (
          <EmptyState
            title="No accounts connected"
            message="Use the mock connector above in development to add an Instagram account."
          />
        ) : null}
        {accounts.length > 0 ? (
          <TableWrap>
            <table className={`${tableClass} min-w-[860px]`}>
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
                  const isReconnecting = reconnectingId === account.id;
                  const isDeleting = deletingId === account.id;

                  return (
                    <>
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
                      <td className={tdClass}>
                        {account.expires_at
                          ? new Date(account.expires_at).toLocaleString()
                          : "Not available"}
                      </td>
                      <td className={tdClass}>
                        {account.updated_at || account.created_at
                          ? new Date(
                              account.updated_at || account.created_at || ""
                            ).toLocaleString()
                          : "Not available"}
                      </td>
                      <td className={`${tdClass} flex flex-wrap gap-2`}>
                        <Button
                          type="button"
                          variant="secondary"
                          className="gap-2"
                          onClick={() => setExpandedId(expandedId === account.id ? null : account.id)}
                        >
                          <Bot className="h-4 w-4" aria-hidden="true" />
                          {account.ai_enabled ? "AI Settings" : "Enable AI"}
                        </Button>
                        {canManageAccounts ? (
                          <Button
                            type="button"
                            variant="secondary"
                            disabled={!isDisconnected || isReconnecting}
                            onClick={() => reconnect(account.id)}
                          >
                            {isReconnecting ? "Redirecting..." : "Reconnect"}
                          </Button>
                        ) : null}
                        {canDisconnectAccounts ? (
                          <Button
                            type="button"
                            variant="danger"
                            disabled={!isConnected}
                            onClick={() => disconnect(account.id)}
                          >
                            Disconnect
                          </Button>
                        ) : null}
                        {canDeleteAccounts ? (
                          <Button
                            type="button"
                            variant="danger"
                            disabled={isDeleting}
                            onClick={() => setConfirmDeleteId(account.id)}
                            title="Permanently delete account and all data"
                          >
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                            <span className="sr-only">Delete</span>
                          </Button>
                        ) : null}
                        {!canManageAccounts && !canDisconnectAccounts && !canDeleteAccounts ? (
                          <span className="text-sm text-muted">Read only</span>
                        ) : null}
                      </td>
                    </tr>
                    {expandedId === account.id ? (
                      <tr>
                        <td colSpan={6} className="bg-white px-5 pb-4">
                          <AISettingsPanel
                            account={account}
                            canManage={canManageAccounts}
                            onSaved={(updated) => {
                              setAccounts((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
                            }}
                          />
                        </td>
                      </tr>
                    ) : null}
                    </>
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
