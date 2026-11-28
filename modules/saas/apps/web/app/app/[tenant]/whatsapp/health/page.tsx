"use client";

import { useState } from "react";

import { manyRequest } from "@/lib/many";
import { PageState } from "@/lib/page-state";
import {
  Button,
  Card,
  ConfirmAction,
  Field,
  Notice,
  PageHeader,
  StatCard,
  StatusBadge,
  Switch,
} from "@/lib/ui";
import {
  formatDate,
  healthFreshness,
  parseKeywords,
  type OutreachHealth,
} from "@/lib/whatsapp-types";

import { actionMessage, useWhatsapp } from "../whatsapp-shell";

import "@/app/whatsapp-screen.css";

type OptInLink = {
  url: string;
  expires_at: string;
  older_links_revoked: boolean;
};

export default function WhatsappHealthPage() {
  const { tenantId, account, health, healthStatus, refreshHealth, notify } =
    useWhatsapp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function requestRefresh() {
    setBusy(true);
    setError(null);
    try {
      await manyRequest(
        { kind: "org", tenantId },
        "POST",
        `whatsapp/accounts/${account.id}/health-refresh`,
      );
      notify("Health refresh queued. The latest stored result is shown below.");
      refreshHealth();
      window.setTimeout(refreshHealth, 2000);
    } catch (caught) {
      setError(actionMessage(caught, "The refresh failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="WhatsApp health"
        purpose="Monitor account quality, sending capacity, health freshness, and safety controls."
        actions={
          <Button
            variant="quiet"
            data-testid="wa-health-refresh"
            disabled={busy}
            onClick={requestRefresh}
          >
            Refresh from Meta
          </Button>
        }
      />
      {error && <Notice message={error} tone="error" scope="item" />}
      <PageState status={healthStatus} homeHref={`/app/${tenantId}`}>
        {health && (
          <div className="wa-stack" data-testid="wa-health">
            <div className="wa-metrics wa-metrics-4">
              <StatCard
                label="Quality rating"
                value={health.quality_rating || "Not available"}
              />
              <StatCard
                label="Messaging tier"
                value={health.messaging_limit_tier || "Not available"}
              />
              <StatCard
                label="Sent / daily cap"
                value={`${health.sent_recipient_count_24h} / ${health.daily_cap}`}
              />
              <StatCard
                label="Health freshness"
                value={healthFreshness(health.health_age_seconds)}
                hint={formatDate(health.health_checked_at)}
              />
            </div>
            <Card title="Safety state">
              <div className="wa-badges">
                <StatusBadge
                  value={health.outreach_enabled ? "active" : "disabled"}
                  tone={health.outreach_enabled ? "success" : "danger"}
                />
                <StatusBadge
                  value={health.outreach_paused ? "paused" : "active"}
                />
              </div>
              <dl className="wa-facts">
                <div>
                  <dt>Global kill switch</dt>
                  <dd>
                    {health.outreach_enabled
                      ? "Enabled — outreach actions are available."
                      : "Disabled — no outreach can be started or resumed."}
                  </dd>
                </div>
                <div>
                  <dt>Account pause reason</dt>
                  <dd dir="auto">
                    {health.outreach_paused_reason || "Not paused"}
                  </dd>
                </div>
              </dl>
            </Card>
            <SettingsForm
              key={settingsKey(health)}
              health={health}
              onSaved={() => {
                notify("Outreach settings saved.");
                refreshHealth();
              }}
            />
            <OptInLinkCard notify={notify} />
          </div>
        )}
      </PageState>
    </>
  );
}

/** The form starts again from the stored values whenever they change (after a save). */
function settingsKey(health: OutreachHealth): string {
  return JSON.stringify([
    health.ctwa_counts_as_consent,
    health.transactional_utility_attested,
    health.opt_in_keywords,
    health.opt_out_keywords,
    health.outreach_daily_cap,
  ]);
}

function SettingsForm({
  health,
  onSaved,
}: {
  health: OutreachHealth;
  onSaved: () => void;
}) {
  const { tenantId, account } = useWhatsapp();
  const [ctwa, setCtwa] = useState(health.ctwa_counts_as_consent);
  const [utility, setUtility] = useState(health.transactional_utility_attested);
  const [optIn, setOptIn] = useState((health.opt_in_keywords || []).join(", "));
  const [optOut, setOptOut] = useState(
    (health.opt_out_keywords || []).join(", "),
  );
  const [cap, setCap] = useState(String(health.outreach_daily_cap));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await manyRequest(
        { kind: "org", tenantId },
        "PATCH",
        `whatsapp/accounts/${account.id}/outreach-settings`,
        {
          ctwa_counts_as_consent: ctwa,
          transactional_utility_attested: utility,
          opt_in_keywords: parseKeywords(optIn),
          opt_out_keywords: parseKeywords(optOut),
          outreach_daily_cap: Number(cap),
        },
      );
      onSaved();
    } catch (caught) {
      setError(actionMessage(caught, "Could not save the settings."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Outreach settings" data-testid="wa-settings">
      <p className="muted">
        These values are the account&apos;s current stored settings.
      </p>
      {error && <Notice message={error} tone="error" scope="item" />}
      <div className="wa-form">
        <Switch
          checked={ctwa}
          onChange={setCtwa}
          data-testid="wa-ctwa"
          label="Click-to-WhatsApp counts as consent"
          hint="Warning: Enable only if the entry point clearly says people agree to marketing messages."
        />
        <Switch
          checked={utility}
          onChange={setUtility}
          data-testid="wa-utility"
          label="Transactional utility attestation"
          hint="Warning: You attest that utility templates are strictly transactional and are not marketing."
        />
        <div className="wa-two">
          <Field
            label="Opt-in keywords"
            hint="Comma-separated. Required before public opt-in links are enabled."
          >
            {(control) => (
              <input
                {...control}
                dir="auto"
                data-testid="wa-opt-in"
                value={optIn}
                placeholder="START, YES"
                onChange={(event) => setOptIn(event.target.value)}
              />
            )}
          </Field>
          <Field label="Opt-out keywords" hint="Comma-separated.">
            {(control) => (
              <input
                {...control}
                dir="auto"
                data-testid="wa-opt-out"
                value={optOut}
                placeholder="STOP, UNSUBSCRIBE"
                onChange={(event) => setOptOut(event.target.value)}
              />
            )}
          </Field>
        </div>
        <Field label="Daily outreach cap">
          {(control) => (
            <input
              {...control}
              type="number"
              min="1"
              max="100000"
              dir="ltr"
              data-testid="wa-cap"
              value={cap}
              onChange={(event) => setCap(event.target.value)}
            />
          )}
        </Field>
        <div className="action-row">
          <Button
            data-testid="wa-settings-save"
            onClick={save}
            disabled={busy || !cap || Number(cap) < 1}
          >
            {busy ? "Saving…" : "Save settings"}
          </Button>
        </div>
      </div>
    </Card>
  );
}

function OptInLinkCard({
  notify,
}: {
  notify: (message: string, tone?: "info" | "error") => void;
}) {
  const { tenantId, account } = useWhatsapp();
  const [rotate, setRotate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<OptInLink | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const result = await manyRequest<OptInLink>(
        { kind: "org", tenantId },
        "POST",
        `whatsapp/accounts/${account.id}/opt-in-link`,
        { rotate },
      );
      setLink(result);
      notify(
        result.older_links_revoked
          ? "New link created; older links were revoked."
          : "Opt-in link created; older links remain valid.",
      );
    } catch (caught) {
      setError(actionMessage(caught, "Could not create the opt-in link."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Public opt-in link" data-testid="wa-optin">
      <p className="muted">
        The link records an unverified request. The contact becomes opted in
        only after sending a configured keyword inbound.
      </p>
      {error && <Notice message={error} tone="error" scope="item" />}
      <div className="wa-form">
        <label className="wa-attest">
          <input
            type="checkbox"
            data-testid="wa-rotate"
            checked={rotate}
            onChange={(event) => setRotate(event.target.checked)}
          />
          <span>
            <strong>Rotate link salt and revoke every older link.</strong> Leave
            this unchecked for normal link retrieval.
          </span>
        </label>
        <div className="action-row">
          {rotate ? (
            <ConfirmAction
              testId="wa-optin-rotate"
              title="Revoke every older opt-in link?"
              description="A new link is created and all links shared earlier stop working."
              confirmLabel="Rotate and create link"
              disabled={busy}
              onConfirm={create}
            >
              Rotate and create link
            </ConfirmAction>
          ) : (
            <Button data-testid="wa-optin-get" onClick={create} disabled={busy}>
              Get opt-in link
            </Button>
          )}
        </div>
        {link && (
          <div className="wa-link" data-testid="wa-optin-result">
            <code dir="ltr">{link.url}</code>
            <p className="muted wa-small">
              Expires {formatDate(link.expires_at)} ·{" "}
              {link.older_links_revoked
                ? "Older links were revoked"
                : "Older links remain valid"}
            </p>
            <Button
              variant="quiet"
              onClick={() =>
                navigator.clipboard
                  .writeText(link.url)
                  .then(() => notify("Link copied."))
                  .catch(() => notify("Could not copy the link.", "error"))
              }
            >
              Copy
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}
