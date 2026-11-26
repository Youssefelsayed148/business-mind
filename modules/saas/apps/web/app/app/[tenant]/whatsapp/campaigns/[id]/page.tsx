"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { manyRequest } from "@/lib/many";
import { PageState } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  Card,
  ConfirmAction,
  Field,
  LinkButton,
  Notice,
  PageHeader,
  StatCard,
  StatusBadge,
} from "@/lib/ui";
import {
  campaignIsFinal,
  formatDate,
  reasonLabel,
  statusLabel,
  statusTone,
  type CampaignStats,
} from "@/lib/whatsapp-types";

import { actionMessage, useWhatsapp } from "../../whatsapp-shell";

import "@/app/whatsapp-screen.css";

const REFRESH_MS = 5000;

export default function WhatsappCampaignPage() {
  const { id } = useParams<{ id: string }>();
  const { tenantId, outreachDisabled, refreshHealth, notify } = useWhatsapp();
  const { data, status, reload } = useManyData<CampaignStats>(
    () =>
      manyRequest(
        { kind: "org", tenantId },
        "GET",
        `whatsapp/campaigns/${id}/stats`,
      ),
    id,
  );
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const final = data ? campaignIsFinal(data.campaign.status) : false;

  // Live numbers while the campaign can still change.
  useEffect(() => {
    if (final) return;
    const timer = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [final, reload]);

  async function act(kind: "pause" | "resume" | "cancel") {
    setBusy(true);
    setError(null);
    try {
      await manyRequest(
        { kind: "org", tenantId },
        "POST",
        `whatsapp/campaigns/${id}/${kind}`,
        kind === "resume" ? { note: note.trim() } : undefined,
      );
      notify(
        `Campaign ${kind === "pause" ? "paused" : kind === "resume" ? "resumed" : "cancelled"}.`,
      );
      setNote("");
      reload();
      refreshHealth();
    } catch (caught) {
      setError(actionMessage(caught, `Could not ${kind} the campaign.`));
    } finally {
      setBusy(false);
    }
  }

  const back = (
    <LinkButton
      href={`/app/${tenantId}/whatsapp/campaigns`}
      variant="ghost"
      icon="arrow-left"
    >
      All campaigns
    </LinkButton>
  );

  return (
    <PageState status={status} homeHref={`/app/${tenantId}/whatsapp/campaigns`}>
      {data && (
        <CampaignBody
          stats={data}
          back={back}
          error={error}
          busy={busy}
          note={note}
          setNote={setNote}
          outreachDisabled={outreachDisabled}
          act={act}
        />
      )}
    </PageState>
  );
}

function CampaignBody({
  stats,
  back,
  error,
  busy,
  note,
  setNote,
  outreachDisabled,
  act,
}: {
  stats: CampaignStats;
  back: React.ReactNode;
  error: string | null;
  busy: boolean;
  note: string;
  setNote: (value: string) => void;
  outreachDisabled: boolean;
  act: (kind: "pause" | "resume" | "cancel") => void;
}) {
  const c = stats.campaign;
  const statuses = stats.recipient_statuses;
  const unknown =
    statuses.outcome_unknown ?? stats.reasons.outcome_unknown ?? 0;
  const metrics = [
    ["Sent", c.sent_count],
    ["Delivered", c.delivered_count],
    ["Read", c.read_count],
    ["Failed", c.failed_count],
    ["Skipped", c.skipped_count],
  ] as const;
  return (
    <div className="wa-stack" data-testid="wa-campaign-detail">
      <PageHeader
        eyebrow={back}
        title={<span dir="auto">{c.name}</span>}
        purpose={`Created ${formatDate(c.created_at)} · live refresh every 5 seconds`}
        actions={
          <StatusBadge value={c.status} tone={statusTone(c.status)}>
            {statusLabel(c.status)}
          </StatusBadge>
        }
      />
      {error && <Notice message={error} tone="error" scope="item" />}
      <div className="wa-metrics" data-testid="wa-metrics">
        {metrics.map(([label, value]) => (
          <StatCard key={label} label={label} value={value} />
        ))}
        <StatCard
          label="Unknown outcomes"
          value={unknown}
          data-testid="wa-unknown"
        />
      </div>
      <p className="muted wa-small">
        Unknown outcomes are not retryable: the provider may have received the
        message but the final result could not be confirmed, so they are
        deliberately not retried to avoid duplicate messages.
      </p>
      <Card title="Recipient status detail">
        {Object.keys(statuses).length === 0 ? (
          <p className="muted">Recipients have not been frozen yet.</p>
        ) : (
          <ul className="wa-counts">
            {Object.entries(statuses).map(([key, count]) => (
              <li key={key}>
                <span>{reasonLabel(key)}</span>
                <strong>{count}</strong>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {Object.keys(stats.reasons).length > 0 && (
        <Card title="Failure and skip reasons">
          <ul className="wa-counts" data-testid="wa-reasons">
            {Object.entries(stats.reasons).map(([reason, count]) => (
              <li key={reason}>
                <span>{reasonLabel(reason)}</span>
                <strong>{count}</strong>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title="Campaign controls">
        <p className="muted">
          Cancel stops future dispatch; pending recipient rows remain for audit
          purposes.
        </p>
        <div className="action-row">
          {c.status === "running" && (
            <Button
              variant="quiet"
              data-testid="wa-pause"
              disabled={busy}
              onClick={() => act("pause")}
            >
              Pause
            </Button>
          )}
          {c.status === "paused" && (
            <>
              <Field label="Resume note" required>
                {(control) => (
                  <input
                    {...control}
                    dir="auto"
                    data-testid="wa-resume-note"
                    value={note}
                    placeholder="Required audited resume note"
                    onChange={(event) => setNote(event.target.value)}
                  />
                )}
              </Field>
              <Button
                data-testid="wa-resume"
                disabled={busy || outreachDisabled || !note.trim()}
                title={
                  outreachDisabled ? "Outreach is globally disabled" : undefined
                }
                onClick={() => act("resume")}
              >
                Resume
              </Button>
            </>
          )}
          {["draft", "scheduled", "running", "paused"].includes(c.status) && (
            <ConfirmAction
              testId="wa-cancel"
              title="Cancel this campaign?"
              description="Future dispatch stops. Pending recipient rows remain for audit purposes."
              confirmLabel="Cancel campaign"
              disabled={busy}
              onConfirm={() => act("cancel")}
            >
              Cancel campaign
            </ConfirmAction>
          )}
        </div>
      </Card>
    </div>
  );
}
