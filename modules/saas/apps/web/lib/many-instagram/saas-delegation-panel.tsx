"use client";

import { useCallback, useEffect, useState } from "react";

import { ManyError } from "@/lib/many";
import { Button, Field, Notice, StatusBadge } from "@/lib/ui";

import { staffGet, staffSend } from "./calls";
import { formatDateTime } from "./helpers";
import type { SaasDelegationConfig, SaasDelegationRetryResult } from "./types";

function plain(caught: unknown, fallback: string) {
  return caught instanceof ManyError ? caught.message : fallback;
}

/**
 * Per-account "delegated mode" settings. The secret is write-only: the API never returns
 * it, so the box always starts empty.
 */
export function SaasDelegationPanel({ accountId }: { accountId: string }) {
  const path = `/instagram/accounts/${encodeURIComponent(accountId)}/saas-delegation`;
  const [config, setConfig] = useState<SaasDelegationConfig | null>(null);
  const [connectionId, setConnectionId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    text: string;
    tone: "info" | "error";
  } | null>(null);

  const adopt = useCallback((next: SaasDelegationConfig) => {
    setConfig(next);
    setConnectionId(next.saas_connection_id ?? "");
    setBaseUrl(next.saas_base_url ?? "");
    setSecret("");
  }, []);

  const load = useCallback(() => {
    setLoadError(null);
    staffGet<SaasDelegationConfig>(path).then(adopt, (caught: unknown) =>
      setLoadError(plain(caught, "Could not load the delegation settings.")),
    );
  }, [path, adopt]);

  useEffect(() => {
    const timer = setTimeout(load, 0);
    return () => clearTimeout(timer);
  }, [load]);

  async function retryFailed() {
    setSaving(true);
    setResult(null);
    try {
      const next = await staffSend<SaasDelegationRetryResult>(
        "POST",
        `${path}/retry-failed`,
      );
      adopt(next);
      setResult({
        text: `${next.requeued} failed event${next.requeued === 1 ? "" : "s"} re-queued.`,
        tone: "info",
      });
    } catch (caught) {
      setResult({
        text: plain(caught, "Could not re-queue the failed events."),
        tone: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  async function save(enabled: boolean | undefined) {
    setSaving(true);
    setResult(null);
    try {
      const body: Record<string, unknown> = {
        saas_connection_id: connectionId,
        saas_base_url: baseUrl,
      };
      if (secret) body.secret = secret;
      if (enabled !== undefined) body.saas_delegation_enabled = enabled;
      adopt(await staffSend<SaasDelegationConfig>("PATCH", path, body));
      setResult({
        text:
          enabled === undefined
            ? "Delegation settings saved."
            : enabled
              ? "Delegation enabled."
              : "Delegation disabled.",
        tone: "info",
      });
    } catch (caught) {
      setResult({
        text: plain(caught, "Could not save the delegation settings."),
        tone: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className="ig-subpanel"
      data-testid="ig-delegation"
      aria-label="SaaS delegation"
    >
      <header className="ig-subpanel-head">
        <div>
          <h3>SaaS delegation</h3>
          <p className="muted">
            When on, the SaaS inbox writes the AI replies for this account. Many
            keeps everything Meta (tokens, webhooks, the messaging window).
            Many&apos;s own AI does not reply while this is on.
          </p>
        </div>
        {config && (
          <div className="ig-badges">
            {config.degraded && (
              <StatusBadge value="failed">Degraded</StatusBadge>
            )}
            <StatusBadge
              value={config.saas_delegation_enabled ? "active" : "paused"}
              data-testid="ig-delegation-state"
            >
              {config.saas_delegation_enabled ? "Delegated" : "Off"}
            </StatusBadge>
          </div>
        )}
      </header>

      {loadError && (
        <Notice
          tone="error"
          message={loadError}
          onRetry={load}
          retryLabel="Try again"
        />
      )}
      {!config && !loadError && <p className="muted">Loading...</p>}

      {config && (
        <>
          <div className="ig-grid-2">
            <Field label="Connection ID">
              {(control) => (
                <input
                  {...control}
                  dir="ltr"
                  maxLength={64}
                  disabled={saving}
                  value={connectionId}
                  onChange={(event) => setConnectionId(event.target.value)}
                />
              )}
            </Field>
            <Field
              label="SaaS base URL"
              hint="https only in production. Private and local hosts are rejected."
            >
              {(control) => (
                <input
                  {...control}
                  dir="ltr"
                  maxLength={512}
                  disabled={saving}
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                />
              )}
            </Field>
          </div>
          <Field
            label="Signing secret"
            hint={
              config.previous_secret_active
                ? `Rotation grace window active until ${formatDateTime(config.previous_secret_expires_at)}; both secrets are accepted.`
                : "At least 32 characters. Never shown again after saving."
            }
          >
            {(control) => (
              <input
                {...control}
                type="password"
                dir="ltr"
                autoComplete="new-password"
                disabled={saving}
                placeholder={
                  config.secret_set
                    ? "Set. Enter a new value to rotate."
                    : "Paste the secret from the SaaS"
                }
                value={secret}
                onChange={(event) => setSecret(event.target.value)}
              />
            )}
          </Field>

          <dl className="ig-facts">
            <div>
              <dt>Last forward</dt>
              <dd>
                {config.last_forward_status ?? "none yet"}
                {config.last_forward_at
                  ? ` · ${formatDateTime(config.last_forward_at)}`
                  : ""}
              </dd>
            </div>
            <div>
              <dt>Queue depth</dt>
              <dd>{config.queue_depth ?? "not measured"}</dd>
            </div>
            <div>
              <dt>Failed events</dt>
              <dd>
                {config.failed_events ?? "not measured"}
                {config.failed_events
                  ? ` (${config.retryable_failed_events ?? 0} can be retried)`
                  : ""}
              </dd>
            </div>
            <div>
              <dt>Health</dt>
              <dd>{config.degraded ? "Degraded" : "No problems reported"}</dd>
            </div>
          </dl>

          <div className="action-row">
            <Button
              variant="quiet"
              disabled={saving}
              data-testid="ig-delegation-save"
              onClick={() => void save(undefined)}
            >
              Save
            </Button>
            {config.saas_delegation_enabled &&
              (config.retryable_failed_events ?? 0) > 0 && (
                <Button
                  variant="quiet"
                  disabled={saving}
                  onClick={() => void retryFailed()}
                >
                  Retry failed events
                </Button>
              )}
            {config.saas_delegation_enabled ? (
              <Button
                variant="quiet"
                disabled={saving}
                onClick={() => void save(false)}
              >
                Disable delegation
              </Button>
            ) : (
              <Button
                disabled={saving}
                data-testid="ig-delegation-enable"
                onClick={() => void save(true)}
              >
                Save and enable
              </Button>
            )}
          </div>
        </>
      )}
      {result && (
        <Notice tone={result.tone} message={result.text} scope="item" />
      )}
    </section>
  );
}
