"use client";

import { useEffect, useState } from "react";

import { manyRequest, type ManyScope } from "@/lib/many";
import { Button, Field, StatusBadge } from "@/lib/ui";

import type { ChannelNote } from "./connect-buttons";
import {
  formatWhen,
  type SaasDelegationConfig,
  type SaasDelegationRetryResult,
} from "./types";

/**
 * "SaaS delegation" of one channel: the SaaS inbox writes the AI replies while Many keeps
 * everything Meta. Admin and Owner only (channels.connect); others do not see the panel.
 * The signing secret is write-only: the API never returns it, so the input starts empty.
 */
export function DelegationPanel({
  scope,
  platform,
  accountId,
  canManage,
  onNote,
}: {
  scope: ManyScope;
  platform: "facebook" | "whatsapp";
  accountId: string;
  canManage: boolean;
  onNote: (note: ChannelNote) => void;
}) {
  const path = `${platform}/accounts/${encodeURIComponent(accountId)}/saas-delegation`;
  const [config, setConfig] = useState<SaasDelegationConfig | null>(null);
  const [connectionId, setConnectionId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  function adopt(next: SaasDelegationConfig) {
    setConfig(next);
    setConnectionId(next.saas_connection_id ?? "");
    setBaseUrl(next.saas_base_url ?? "");
    setSecret("");
  }

  useEffect(() => {
    if (!canManage) return;
    let cancelled = false;
    manyRequest<SaasDelegationConfig>(scope, "GET", path).then(
      (next) => {
        if (!cancelled) adopt(next);
      },
      (caught: unknown) => {
        if (!cancelled)
          setLoadError(
            caught instanceof Error && caught.message
              ? caught.message
              : "Could not load the delegation settings.",
          );
      },
    );
    return () => {
      cancelled = true;
    };
    // scope is rebuilt per render; the tenant id and path say when to load again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, canManage, scope.kind === "org" ? scope.tenantId : "staff"]);

  if (!canManage) return null;

  async function retryFailed() {
    setSaving(true);
    try {
      const result = await manyRequest<SaasDelegationRetryResult>(
        scope,
        "POST",
        `${path}/retry-failed`,
      );
      adopt(result);
      onNote({
        tone: "info",
        text: `${result.requeued} failed event${result.requeued === 1 ? "" : "s"} re-queued.`,
      });
    } catch (caught) {
      onNote({
        tone: "error",
        text:
          caught instanceof Error && caught.message
            ? caught.message
            : "Could not re-queue the failed events.",
      });
    } finally {
      setSaving(false);
    }
  }

  async function save(enabled: boolean | undefined) {
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        saas_connection_id: connectionId,
        saas_base_url: baseUrl,
      };
      if (secret) body.secret = secret;
      if (enabled !== undefined) body.saas_delegation_enabled = enabled;
      adopt(
        await manyRequest<SaasDelegationConfig>(scope, "PATCH", path, body),
      );
      onNote({
        tone: "info",
        text:
          enabled === undefined
            ? "Delegation settings saved."
            : enabled
              ? "Delegation enabled."
              : "Delegation disabled.",
      });
    } catch (caught) {
      onNote({
        tone: "error",
        text:
          caught instanceof Error && caught.message
            ? caught.message
            : "Could not save the delegation settings.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className="mc-panel"
      data-testid={`delegation-${accountId}`}
      aria-label="SaaS delegation"
    >
      <header className="mc-panel-head">
        <div>
          <h3>SaaS delegation</h3>
          <p className="field-hint">
            When on, the SaaS inbox writes the AI replies for this channel. Many
            keeps everything Meta (tokens, webhooks, the messaging window,
            templates) and its own AI does not reply while this is on.
          </p>
        </div>
        {config && (
          <div className="mc-badges">
            {config.degraded && <StatusBadge value="degraded" tone="danger" />}
            <StatusBadge
              value={config.saas_delegation_enabled ? "delegated" : "off"}
              tone={config.saas_delegation_enabled ? "success" : "neutral"}
            />
          </div>
        )}
      </header>

      {loadError && (
        <p className="field-error" role="alert">
          {loadError}
        </p>
      )}

      {config ? (
        <>
          <div className="mc-grid">
            <Field label="Connection ID">
              {(control) => (
                <input
                  {...control}
                  dir="ltr"
                  value={connectionId}
                  maxLength={64}
                  disabled={saving}
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
                  value={baseUrl}
                  maxLength={512}
                  disabled={saving}
                  onChange={(event) => setBaseUrl(event.target.value)}
                />
              )}
            </Field>
          </div>
          <Field
            label="Signing secret"
            hint={
              config.previous_secret_active
                ? `Rotation grace window active until ${formatWhen(config.previous_secret_expires_at)}; both secrets are accepted.`
                : "At least 32 characters. Never shown again after saving."
            }
          >
            {(control) => (
              <input
                {...control}
                type="password"
                dir="ltr"
                autoComplete="new-password"
                placeholder={
                  config.secret_set
                    ? "Set. Enter a new value to rotate it."
                    : "Paste the secret from the SaaS"
                }
                value={secret}
                disabled={saving}
                onChange={(event) => setSecret(event.target.value)}
              />
            )}
          </Field>

          <dl className="mc-facts">
            <div>
              <dt>Last forward</dt>
              <dd>
                {config.last_forward_status ?? "none yet"}
                {config.last_forward_at
                  ? ` · ${formatWhen(config.last_forward_at)}`
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

          <div className="mc-actions">
            <Button
              variant="quiet"
              data-testid="delegation-save"
              disabled={saving}
              onClick={() => void save(undefined)}
            >
              Save
            </Button>
            {config.saas_delegation_enabled &&
              (config.retryable_failed_events ?? 0) > 0 && (
                <Button
                  variant="quiet"
                  data-testid="delegation-retry"
                  disabled={saving}
                  onClick={() => void retryFailed()}
                >
                  Retry failed events
                </Button>
              )}
            {config.saas_delegation_enabled ? (
              <Button
                variant="quiet"
                data-testid="delegation-disable"
                disabled={saving}
                onClick={() => void save(false)}
              >
                Disable delegation
              </Button>
            ) : (
              <Button
                data-testid="delegation-enable"
                disabled={saving}
                onClick={() => void save(true)}
              >
                Save and enable
              </Button>
            )}
          </div>
        </>
      ) : (
        !loadError && <p className="muted">Loading...</p>
      )}
    </section>
  );
}
