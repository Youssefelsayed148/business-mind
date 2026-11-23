"use client";

import { useEffect, useState } from "react";
import { Copy, Link as LinkIcon, RefreshCw } from "lucide-react";
import { useWhatsapp } from "@/components/whatsapp/WhatsappShell";
import { useToast } from "@/components/ToastProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/whatsapp";
import { useWorkspaceAdmin } from "@/lib/workspacePermissions";

export default function HealthPage() {
  const { account, health, refreshHealth } = useWhatsapp();
  const isAdmin = useWorkspaceAdmin();
  const [ctwa, setCtwa] = useState(false);
  const [utility, setUtility] = useState(false);
  const [optIn, setOptIn] = useState("");
  const [optOut, setOptOut] = useState("");
  const [cap, setCap] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<{
    url: string;
    expires_at: string;
    older_links_revoked: boolean;
  } | null>(null);
  const [rotate, setRotate] = useState(false);
  const toast = useToast();

  useEffect(() => {
    if (!health) return;
    setCtwa(health.ctwa_counts_as_consent);
    setUtility(health.transactional_utility_attested);
    setOptIn((health.opt_in_keywords || []).join(", "));
    setOptOut((health.opt_out_keywords || []).join(", "));
    setCap(String(health.outreach_daily_cap));
  }, [health]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/whatsapp/accounts/${account!.id}/outreach-settings`, {
        ctwa_counts_as_consent: ctwa,
        transactional_utility_attested: utility,
        opt_in_keywords: optIn
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        opt_out_keywords: optOut
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        outreach_daily_cap: Number(cap),
      });
      toast.success("Outreach settings saved.");
      await refreshHealth();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Could not save settings";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function requestHealthRefresh() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/whatsapp/accounts/${account!.id}/health-refresh`);
      toast.info(
        "Health refresh queued. The latest stored result is shown below.",
      );
      await refreshHealth();
      window.setTimeout(() => void refreshHealth(), 2000);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Refresh failed";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function createLink() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<{
        url: string;
        expires_at: string;
        older_links_revoked: boolean;
      }>(`/whatsapp/accounts/${account!.id}/opt-in-link`, { rotate });
      setLink(result);
      toast.success(
        result.older_links_revoked
          ? "New link created; older links were revoked."
          : "Opt-in link created; older links remain valid.",
      );
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Could not create opt-in link";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  if (!health) return <DataState loading />;

  const freshness =
    health.health_age_seconds == null
      ? "Never checked"
      : health.health_age_seconds < 300
        ? "Fresh"
        : health.health_age_seconds < 1800
          ? "A few minutes old"
          : "Stale";

  return (
    <div className="grid gap-6">
      <PageHeader
        title="WhatsApp health"
        description="Monitor account quality, sending capacity, health freshness, and safety controls."
      >
        <Button
          variant="secondary"
          className="gap-2"
          onClick={requestHealthRefresh}
          disabled={busy || !isAdmin}
          title={
            !isAdmin ? "Workspace admin permission is required" : undefined
          }
        >
          <RefreshCw className="h-4 w-4" /> Refresh from Meta
        </Button>
      </PageHeader>
      <DataState error={error} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label="Quality rating"
          value={health.quality_rating || "Not available"}
        />
        <Metric
          label="Messaging tier"
          value={health.messaging_limit_tier || "Not available"}
        />
        <Metric
          label="Sent / daily cap"
          value={`${health.sent_recipient_count_24h} / ${health.daily_cap}`}
        />
        <Metric
          label="Health freshness"
          value={freshness}
          detail={formatDate(health.health_checked_at)}
        />
      </div>
      <Panel>
        <h2 className="text-lg font-bold">Safety state</h2>
        <div className="mt-4 flex flex-wrap gap-3">
          <Badge value={health.outreach_enabled ? "active" : "disabled"} />
          <Badge value={health.outreach_paused ? "paused" : "active"} />
        </div>
        <dl className="mt-4 grid gap-2 text-sm">
          <div>
            <dt className="font-semibold">Global kill switch</dt>
            <dd className="text-muted">
              {health.outreach_enabled
                ? "Enabled — outreach actions are available."
                : "Disabled — no outreach can be started or resumed."}
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Account pause reason</dt>
            <dd className="text-muted" dir="auto">
              {health.outreach_paused_reason || "Not paused"}
            </dd>
          </div>
        </dl>
      </Panel>
      {isAdmin ? (
        <>
          <Panel>
            <h2 className="text-lg font-bold">Outreach settings</h2>
            <p className="mt-1 text-sm text-muted">
              These values are the account&apos;s current stored settings.
            </p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="flex items-start gap-3 rounded-lg border border-line p-4 text-sm font-semibold">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={ctwa}
                  onChange={(event) => setCtwa(event.target.checked)}
                />
                <span>
                  Click-to-WhatsApp counts as consent
                  <span className="mt-1 block text-xs font-normal text-amber-700">
                    Warning: Enable only if the entry point clearly says people
                    agree to marketing messages.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-3 rounded-lg border border-line p-4 text-sm font-semibold">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={utility}
                  onChange={(event) => setUtility(event.target.checked)}
                />
                <span>
                  Transactional utility attestation
                  <span className="mt-1 block text-xs font-normal text-amber-700">
                    Warning: You attest that utility templates are strictly
                    transactional and are not marketing.
                  </span>
                </span>
              </label>
              <label className="grid gap-1 text-sm font-semibold">
                Opt-in keywords
                <input
                  className="h-10 rounded-lg border border-line px-3 font-normal"
                  value={optIn}
                  onChange={(event) => setOptIn(event.target.value)}
                  placeholder="START, YES"
                />
                <span className="text-xs font-normal text-muted">
                  Comma-separated. Required before public opt-in links are
                  enabled.
                </span>
              </label>
              <label className="grid gap-1 text-sm font-semibold">
                Opt-out keywords
                <input
                  className="h-10 rounded-lg border border-line px-3 font-normal"
                  value={optOut}
                  onChange={(event) => setOptOut(event.target.value)}
                  placeholder="STOP, UNSUBSCRIBE"
                />
              </label>
              <label className="grid gap-1 text-sm font-semibold">
                Daily outreach cap
                <input
                  type="number"
                  min="1"
                  max="100000"
                  className="h-10 rounded-lg border border-line px-3 font-normal"
                  value={cap}
                  onChange={(event) => setCap(event.target.value)}
                />
              </label>
            </div>
            <Button
              className="mt-5"
              onClick={save}
              disabled={busy || !cap || Number(cap) < 1}
            >
              Save settings
            </Button>
          </Panel>
          <Panel>
            <h2 className="text-lg font-bold">Public opt-in link</h2>
            <p className="mt-1 text-sm text-muted">
              The link records an unverified request. The contact becomes opted
              in only after sending a configured keyword inbound.
            </p>
            <label className="mt-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={rotate}
                onChange={(event) => setRotate(event.target.checked)}
              />
              <span>
                <strong>Rotate link salt and revoke every older link.</strong>{" "}
                Leave this unchecked for normal link retrieval.
              </span>
            </label>
            <Button className="mt-4 gap-2" onClick={createLink} disabled={busy}>
              <LinkIcon className="h-4 w-4" />{" "}
              {rotate ? "Rotate and create link" : "Get opt-in link"}
            </Button>
            {link ? (
              <div className="mt-4 rounded-lg bg-slate-50 p-4">
                <p className="break-all font-mono text-xs">{link.url}</p>
                <p className="mt-2 text-xs text-muted">
                  Expires {formatDate(link.expires_at)} ·{" "}
                  {link.older_links_revoked
                    ? "Older links were revoked"
                    : "Older links remain valid"}
                </p>
                <Button
                  variant="secondary"
                  className="mt-3 gap-2"
                  onClick={() =>
                    navigator.clipboard
                      .writeText(link.url)
                      .then(() => toast.success("Link copied."))
                  }
                >
                  <Copy className="h-4 w-4" /> Copy
                </Button>
              </div>
            ) : null}
          </Panel>
        </>
      ) : (
        <Panel>
          <h2 className="font-bold">Admin settings</h2>
          <p className="mt-1 text-sm text-muted">
            Only workspace owners and admins can edit outreach settings or
            create opt-in links.
          </p>
        </Panel>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <Panel className="p-4">
      <p className="text-xs font-bold uppercase text-muted">{label}</p>
      <p className="mt-2 text-xl font-bold" dir="auto">
        {value}
      </p>
      {detail ? <p className="mt-1 text-xs text-muted">{detail}</p> : null}
    </Panel>
  );
}
