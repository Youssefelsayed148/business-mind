"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useWhatsapp } from "@/components/whatsapp/WhatsappShell";
import { useToast } from "@/components/ToastProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import { formatDate, reasonLabel, type CampaignStats } from "@/lib/whatsapp";
import { useWorkspaceCan } from "@/lib/workspacePermissions";
export default function CampaignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { outreachDisabled, refreshHealth } = useWhatsapp();
  const canRun = useWorkspaceCan("run_campaigns");
  const [stats, setStats] = useState<CampaignStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const load = useCallback(
    () =>
      api
        .get<CampaignStats>(`/whatsapp/campaigns/${id}/stats`)
        .then(setStats)
        .catch((e) =>
          setError(
            e instanceof Error ? e.message : "Could not load campaign stats",
          ),
        )
        .finally(() => setLoading(false)),
    [id],
  );
  useEffect(() => {
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, [load]);
  async function action(kind: "pause" | "resume" | "cancel") {
    setBusy(true);
    setError(null);
    try {
      await api.post(
        `/whatsapp/campaigns/${id}/${kind}`,
        kind === "resume" ? { note: note.trim() } : undefined,
      );
      toast.success(
        `Campaign ${kind === "pause" ? "paused" : kind === "resume" ? "resumed" : "cancelled"}.`,
      );
      setNote("");
      await Promise.all([load(), refreshHealth()]);
    } catch (e) {
      const m = e instanceof Error ? e.message : `Could not ${kind}`;
      setError(m);
      toast.error(m);
    } finally {
      setBusy(false);
    }
  }
  if (!stats) return <DataState loading={loading} error={error} />;
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
    <div className="grid gap-6">
      <PageHeader
        title={c.name}
        description={`Created ${formatDate(c.created_at)} · live refresh every 5 seconds`}
      >
        <Badge value={c.status} />
      </PageHeader>
      <DataState error={error} />
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {metrics.map(([label, value]) => (
          <Panel key={label} className="p-4">
            <p className="text-xs font-bold uppercase text-muted">{label}</p>
            <p className="mt-2 text-3xl font-bold">{value}</p>
          </Panel>
        ))}
        <Panel className="border-violet-200 bg-violet-50 p-4">
          <p className="text-xs font-bold uppercase text-violet-700">
            Unknown outcomes
          </p>
          <p className="mt-2 text-3xl font-bold text-violet-950">{unknown}</p>
          <p className="mt-1 text-xs font-semibold text-violet-800">
            Not retryable
          </p>
        </Panel>
      </div>
      <Panel>
        <h2 className="text-lg font-bold">Recipient status detail</h2>
        <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(statuses).map(([status, count]) => (
            <div
              key={status}
              className="flex items-center justify-between rounded-lg border border-line p-3"
            >
              <span>{reasonLabel(status)}</span>
              <strong>{count}</strong>
            </div>
          ))}
        </div>
        {Object.keys(statuses).length === 0 ? (
          <p className="mt-3 text-sm text-muted">
            Recipients have not been frozen yet.
          </p>
        ) : null}
        <p className="mt-4 text-sm text-muted">
          Unknown outcomes mean the provider may have received the message but
          the final result could not be confirmed. They are deliberately not
          retried to avoid duplicate messages.
        </p>
      </Panel>
      {Object.keys(stats.reasons).length ? (
        <Panel>
          <h2 className="text-lg font-bold">Failure and skip reasons</h2>
          <ul className="mt-3 grid gap-2">
            {Object.entries(stats.reasons).map(([reason, count]) => (
              <li
                key={reason}
                className="flex justify-between rounded-lg bg-slate-50 p-3 text-sm"
              >
                <span>{reasonLabel(reason)}</span>
                <strong>{count}</strong>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      {canRun ? (
        <Panel>
          <h2 className="text-lg font-bold">Campaign controls</h2>
          <p className="mt-1 text-sm text-muted">
            Cancel stops future dispatch; pending recipient rows remain for
            audit purposes.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {c.status === "running" ? (
              <Button
                variant="pause"
                onClick={() => action("pause")}
                disabled={busy}
              >
                Pause
              </Button>
            ) : null}
            {c.status === "paused" ? (
              <>
                <input
                  className="h-10 min-w-72 rounded-lg border border-line px-3 text-sm"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Required audited resume note"
                />
                <Button
                  onClick={() => action("resume")}
                  disabled={busy || outreachDisabled || !note.trim()}
                  title={
                    outreachDisabled
                      ? "Outreach is globally disabled"
                      : undefined
                  }
                >
                  Resume
                </Button>
              </>
            ) : null}
            {["draft", "scheduled", "running", "paused"].includes(c.status) ? (
              <Button
                variant="danger"
                onClick={() => action("cancel")}
                disabled={busy}
              >
                Cancel campaign
              </Button>
            ) : null}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
