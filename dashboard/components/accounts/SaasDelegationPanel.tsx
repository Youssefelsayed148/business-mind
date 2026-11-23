"use client";

import { useEffect, useState } from "react";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api";
import type { SaasDelegationConfig, SaasDelegationRetryResult } from "@/lib/types";

// Per-channel "delegated mode" settings. `accountPath` is the channel's
// account URL, e.g. /whatsapp/accounts/<id>. The secret is write-only: the
// API never returns it, so the input always starts empty.
export function SaasDelegationPanel({ accountPath, canManage }: { accountPath: string; canManage: boolean }) {
  const path = `${accountPath}/saas-delegation`;
  const [config, setConfig] = useState<SaasDelegationConfig | null>(null);
  const [connectionId, setConnectionId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const toast = useToast();

  function adopt(next: SaasDelegationConfig) {
    setConfig(next);
    setConnectionId(next.saas_connection_id ?? "");
    setBaseUrl(next.saas_base_url ?? "");
    setSecret("");
  }

  useEffect(() => {
    if (!canManage) return;
    let cancelled = false;
    api
      .get<SaasDelegationConfig>(path)
      .then((next) => {
        if (!cancelled) adopt(next);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "Failed to load SaaS delegation settings");
      });
    return () => {
      cancelled = true;
    };
  }, [path, canManage]);

  if (!canManage) return null;

  async function retryFailed() {
    setSaving(true);
    try {
      const result = await api.post<SaasDelegationRetryResult>(`${path}/retry-failed`);
      adopt(result);
      toast.success(`${result.requeued} failed event${result.requeued === 1 ? "" : "s"} re-queued.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to re-queue failed events");
    } finally {
      setSaving(false);
    }
  }

  async function save(enabled: boolean | undefined) {
    setSaving(true);
    try {
      const body: Record<string, unknown> = { saas_connection_id: connectionId, saas_base_url: baseUrl };
      if (secret) body.secret = secret;
      if (enabled !== undefined) body.saas_delegation_enabled = enabled;
      adopt(await api.patch<SaasDelegationConfig>(path, body));
      toast.success(enabled === undefined ? "SaaS delegation settings saved." : enabled ? "SaaS delegation enabled." : "SaaS delegation disabled.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save SaaS delegation settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-4 grid gap-4 rounded-lg border border-line/70 bg-slate-50/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-bold text-ink">SaaS delegation</h4>
          <p className="text-xs text-muted">
            When on, an external SaaS writes the AI replies for this channel. Many keeps everything Meta
            (tokens, webhooks, the messaging window, templates). Many&apos;s own AI does not reply while this is on.
          </p>
        </div>
        {config ? (
          <div className="flex items-center gap-2">
            {config.degraded ? (
              <span className="rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-700">
                Degraded
              </span>
            ) : null}
            <span className="rounded-full border border-line bg-white px-2.5 py-1 text-xs font-semibold text-ink">
              {config.saas_delegation_enabled ? "Delegated" : "Off"}
            </span>
          </div>
        ) : null}
      </div>

      {loadError ? <p className="text-sm text-red-700">{loadError}</p> : null}

      {config ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Connection ID"
              value={connectionId}
              maxLength={64}
              disabled={saving}
              onChange={(e) => setConnectionId(e.target.value)}
            />
            <Field
              label="SaaS base URL"
              hint="https only in production. Private and local hosts are rejected."
              value={baseUrl}
              maxLength={512}
              disabled={saving}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </div>
          <Field
            label="Signing secret"
            type="password"
            autoComplete="new-password"
            placeholder={config.secret_set ? "•••••••• (set — enter a new value to rotate)" : "Paste the secret from the SaaS"}
            hint={
              config.previous_secret_active
                ? `Rotation grace window active until ${new Date(config.previous_secret_expires_at ?? "").toLocaleString()}; both secrets are accepted.`
                : "At least 32 characters. Never shown again after saving."
            }
            value={secret}
            disabled={saving}
            onChange={(e) => setSecret(e.target.value)}
          />

          <dl className="grid gap-2 text-xs text-muted sm:grid-cols-4">
            <div>
              <dt className="font-semibold text-ink">Last forward</dt>
              <dd>
                {config.last_forward_status ?? "none yet"}
                {config.last_forward_at ? ` · ${new Date(config.last_forward_at).toLocaleString()}` : ""}
              </dd>
            </div>
            <div>
              <dt className="font-semibold text-ink">Queue depth</dt>
              <dd>{config.queue_depth ?? "not measured"}</dd>
            </div>
            <div>
              <dt className="font-semibold text-ink">Failed events</dt>
              <dd>
                {config.failed_events ?? "not measured"}
                {config.failed_events ? ` (${config.retryable_failed_events ?? 0} can be retried)` : ""}
              </dd>
            </div>
            <div>
              <dt className="font-semibold text-ink">Health</dt>
              <dd>{config.degraded ? "Degraded" : "No problems reported"}</dd>
            </div>
          </dl>

          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" disabled={saving} onClick={() => save(undefined)}>
              Save
            </Button>
            {config.saas_delegation_enabled && (config.retryable_failed_events ?? 0) > 0 ? (
              <Button type="button" variant="secondary" disabled={saving} onClick={retryFailed}>
                Retry failed events
              </Button>
            ) : null}
            {config.saas_delegation_enabled ? (
              <Button type="button" variant="secondary" disabled={saving} onClick={() => save(false)}>
                Disable delegation
              </Button>
            ) : (
              <Button type="button" disabled={saving} onClick={() => save(true)}>
                Save and enable
              </Button>
            )}
          </div>
        </>
      ) : loadError ? null : (
        <p className="text-sm text-muted">Loading…</p>
      )}
    </div>
  );
}
