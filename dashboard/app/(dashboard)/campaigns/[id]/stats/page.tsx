"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Badge, statusLabel } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import type { CampaignStats } from "@/lib/types";

function formatDateTime(value?: string | null): string {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function targetLabel(stats: CampaignStats): string {
  if (stats.target_scope !== "specific_media") return "Any media";
  const type = stats.target_media_type && stats.target_media_type !== "unknown"
    ? stats.target_media_type.charAt(0).toUpperCase() + stats.target_media_type.slice(1)
    : "Instagram post";
  const fallback = stats.target_media_type === "reel" ? "Instagram reel" : "Instagram post";
  return [type, stats.target_media_label || fallback].join(" \u00b7 ");
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-bold uppercase text-slate-500">{label}</div>
      <div className="mt-1 min-w-0 break-words text-sm font-semibold text-ink">{value || "Unknown"}</div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <Panel className="relative overflow-hidden">
      <div className="absolute inset-x-0 top-0 h-1 bg-accent" />
      <p className="text-sm font-medium text-muted">{label}</p>
      <p className="mt-2 text-3xl font-bold text-ink">{value}</p>
    </Panel>
  );
}

export default function CampaignStatsPage({ params }: { params: { id: string } }) {
  const [stats, setStats] = useState<CampaignStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const load = useCallback(() => {
    setLoading(true);
    api.get<CampaignStats>(`/campaigns/${params.id}/stats`)
      .then(setStats)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load stats"))
      .finally(() => setLoading(false));
  }, [params.id]);

  useEffect(() => {
    load();
  }, [load]);

  async function retryFailed() {
    if (!stats) return;
    try {
      await Promise.all(stats.recent_messages.filter((message) => message.status === "failed").map((message) => api.post(`/messages/${message.id}/retry`)));
      toast.success("Failed messages queued for retry.");
      load();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to retry messages";
      setError(message);
      toast.error(message);
    }
  }

  return (
    <div className="grid min-w-0 gap-6">
      <PageHeader title={stats ? stats.name : "Campaign Details"}>
        <Button type="button" variant="secondary" onClick={retryFailed}>Retry failed</Button>
      </PageHeader>
      <DataState loading={loading} error={error} />
      {stats ? (
        <>
          <Panel>
            <div className="mb-5 flex flex-wrap items-center gap-2">
              <Badge value={stats.status} />
              <Badge value={stats.delivery_mode} />
              <span className="text-sm font-semibold text-muted">Created {formatDateTime(stats.created_at)}</span>
            </div>
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              <Detail label="Created by" value={stats.created_by || "Unknown"} />
              <Detail label="Instagram account" value={stats.account_username || stats.account_ig_user_id || "Unknown"} />
              <Detail
                label="Target"
                value={(
                  <span>
                    {targetLabel(stats)}
                    {stats.target_media_url ? (
                      <a href={stats.target_media_url} target="_blank" rel="noreferrer" className="mt-1 block truncate text-xs font-medium text-accent hover:underline">
                        {stats.target_media_url}
                      </a>
                    ) : null}
                  </span>
                )}
              />
              <Detail label="Match type" value={statusLabel(stats.match_type)} />
              <Detail label="Cooldown period" value={`${stats.cooldown_hours} hours`} />
              <Detail
                label="Keywords"
                value={stats.keywords.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {stats.keywords.map((keyword) => (
                      <span key={keyword} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700">{keyword}</span>
                    ))}
                  </div>
                ) : "No keywords"}
              />
            </div>
          </Panel>

          <Panel>
            <h2 className="mb-4 text-lg font-bold text-ink">Message</h2>
            <div className="grid gap-4">
              <Detail label="Final DM message/template" value={<pre className="whitespace-pre-wrap rounded-lg border border-line bg-slate-50 p-3 font-sans text-sm font-medium text-slate-800">{stats.message_template}</pre>} />
              <Detail label="Link URL" value={stats.link_url ? <a href={stats.link_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">{stats.link_url}</a> : "Not configured"} />
              <p className="text-sm font-medium text-muted">Supported variables include username, campaign name, keyword, link, and media URL.</p>
            </div>
          </Panel>

          {stats.delivery_mode === "follow_prompt" ? (
            <Panel>
              <h2 className="mb-4 text-lg font-bold text-ink">Follow prompt</h2>
              <div className="grid gap-4 md:grid-cols-2">
                <Detail label="Card title" value={stats.follow_prompt_title || "Unknown"} />
                <Detail label="Profile URL" value={stats.follow_prompt_profile_url ? <a href={stats.follow_prompt_profile_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">{stats.follow_prompt_profile_url}</a> : "Unknown"} />
                <Detail label="Card description" value={stats.follow_prompt_description || "Unknown"} />
                <Detail label="Button and delay" value="Follow, then final message after 10 seconds" />
              </div>
              <p className="mt-4 text-sm font-medium text-muted">The system does not verify whether the user followed.</p>
            </Panel>
          ) : null}

          <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
            <Metric label="Total triggers" value={stats.total_triggers} />
            <Metric label="Successful sends" value={stats.successful_sends} />
            <Metric label="Failed sends" value={stats.failed_sends} />
            <Metric label="New leads" value={stats.new_leads} />
            <Metric label="Last triggered" value={formatDateTime(stats.last_triggered_at)} />
            <Metric label="Cooldowns" value={stats.cooldowns} />
          </div>

          <Panel>
            <h2 className="mb-4 text-lg font-bold text-ink">Recent messages</h2>
            <div className="grid gap-3">
              {stats.recent_messages.length === 0 ? <EmptyState title="No recent messages" /> : null}
              {stats.recent_messages.map((message) => (
                <div key={message.id} className="grid gap-2 rounded-xl border border-line bg-white p-3 text-sm shadow-sm">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <Badge value={message.status} />
                    <span className="font-semibold text-ink">{message.username || "Unknown user"}</span>
                    <span className="text-muted">{formatDateTime(message.sent_at || message.created_at)}</span>
                  </div>
                  {message.error_message ? <p className="text-red-700">{message.error_message}</p> : <p className="text-muted">{statusLabel(message.message_type || "final_delivery")}</p>}
                  <details className="text-xs text-muted">
                    <summary className="cursor-pointer font-semibold text-slate-600">Technical details</summary>
                    <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-50 p-2">{JSON.stringify(message, null, 2)}</pre>
                  </details>
                </div>
              ))}
            </div>
          </Panel>

          <Panel>
            <h2 className="mb-4 text-lg font-bold text-ink">Recent logs</h2>
            <div className="grid gap-3 text-sm">
              {stats.recent_logs.length === 0 ? <EmptyState title="No recent logs" /> : null}
              {stats.recent_logs.map((log) => (
                <div key={log.id} className="rounded-xl border border-line bg-white p-3 shadow-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-ink">{statusLabel(log.event_type)}</span>
                    <span className="text-muted">{formatDateTime(log.created_at)}</span>
                  </div>
                  <p className="mt-1 text-muted">{log.message}</p>
                  <details className="mt-2 text-xs text-muted">
                    <summary className="cursor-pointer font-semibold text-slate-600">Technical details</summary>
                    <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-50 p-2">{JSON.stringify(log.metadata, null, 2)}</pre>
                  </details>
                </div>
              ))}
            </div>
          </Panel>
        </>
      ) : !loading ? (
        <EmptyState title="Campaign not found" message="The campaign details could not be loaded." />
      ) : null}
      <Link href="/campaigns" className="text-sm font-semibold text-accent hover:underline">Back to campaigns</Link>
    </div>
  );
}
