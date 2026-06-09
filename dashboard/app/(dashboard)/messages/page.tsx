"use client";

import { useEffect, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { TableWrap, tableClass, tdClass, thClass, theadRowClass, trClass } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { useCan } from "@/lib/permissions";
import { useToast } from "@/components/ToastProvider";
import type { Campaign, Lead, Message } from "@/lib/types";

function TriggerChip({ value }: { value?: string | null }) {
  if (!value) {
    return <span className="text-muted">Not available</span>;
  }

  return (
    <span dir="auto" className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 font-mono text-xs font-semibold text-slate-700">
      {value}
    </span>
  );
}

function RetryMeta({ message }: { message: Message }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700">
        {message.retry_count} {message.retry_count === 1 ? "retry" : "retries"}
      </span>
      {message.error_message ? <span className="text-red-700">{message.error_message}</span> : <span className="text-muted">No error</span>}
    </div>
  );
}

function MessageTypeBadge({ value }: { value?: string | null }) {
  const isFollowPrompt = value === "follow_prompt";
  const isRetry = value === "retry";
  return (
    <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${isFollowPrompt ? "border-violet-200 bg-violet-50 text-violet-700" : isRetry ? "border-amber-200 bg-amber-50 text-amber-700" : "border-slate-200 bg-slate-50 text-slate-700"}`}>
      {isFollowPrompt ? "Follow Prompt" : isRetry ? "Retry" : "Final Delivery"}
    </span>
  );
}

export default function MessagesPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [campaigns, setCampaigns] = useState<Record<string, string>>({});
  const [leads, setLeads] = useState<Record<string, string>>({});
  const [retrying, setRetrying] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const canRetryMessages = useCan("retry_messages");
  const toast = useToast();

  async function load() {
    setLoading(true);
    try {
      const [messageData, campaignData, leadData] = await Promise.all([
        api.get<Message[]>("/messages"),
        api.get<Campaign[]>("/campaigns"),
        api.get<Lead[]>("/leads"),
      ]);
      setMessages(messageData);
      setCampaigns(Object.fromEntries(campaignData.map((campaign) => [campaign.id, campaign.name])));
      setLeads(Object.fromEntries(leadData.map((lead) => [lead.id, lead.username || lead.ig_user_id])));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load messages");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function retry(id: string) {
    setError(null);
    setRetrying((next) => ({ ...next, [id]: true }));
    try {
      await api.post(`/messages/${id}/retry`);
      toast.success("Message retry queued.");
      await load();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to retry message";
      setError(message);
      toast.error(message);
    } finally {
      setRetrying((next) => {
        const copy = { ...next };
        delete copy[id];
        return copy;
      });
    }
  }

  return (
    <div className="grid gap-6">
      <PageHeader title="Messages" description="Inspect delivery records and retry failed messages when available." />
      <Panel>
        <div className="mb-4">
          <h2 className="text-lg font-bold text-ink">Message delivery</h2>
          <p className="mt-1 text-sm text-muted">Review campaign message outcomes, retries, and provider errors.</p>
        </div>
        <DataState loading={loading} error={error} />
        {loading ? <TableSkeleton rows={5} columns={7} /> : null}
        {!loading && !error && messages.length === 0 ? <EmptyState title="No messages yet" message="Message delivery records will appear after campaign triggers." /> : null}
        {messages.length > 0 ? (
        <TableWrap>
          <table className={`${tableClass} min-w-[980px] border-separate border-spacing-y-2`}>
            <thead>
              <tr className={theadRowClass}>
                <th className={thClass}>Status</th>
                <th className={thClass}>Campaign</th>
                <th className={thClass}>Lead / Username</th>
                <th className={thClass}>Trigger Keyword</th>
                <th className={thClass}>Message Type</th>
                <th className={thClass}>Sent at</th>
                <th className={thClass}>Error / Retry</th>
              </tr>
            </thead>
            <tbody>
              {messages.map((message) => (
                <tr key={message.id} className={`${trClass} rounded-xl bg-white shadow-sm shadow-slate-200/50 hover:bg-white hover:shadow-md`}>
                  <td className={`${tdClass} rounded-l-xl border-y border-l border-line/80`}>
                    <div className="flex min-w-[110px] flex-col items-start gap-2">
                      <Badge value={message.status} />
                    </div>
                  </td>
                  <td className={`${tdClass} border-y border-line/80 font-semibold text-ink`}>
                    <div className="flex min-w-[180px] items-center gap-2">
                      <Avatar label={campaigns[message.campaign_id] || message.campaign_id} size="sm" />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-bold text-ink">{campaigns[message.campaign_id] || message.campaign_id}</div>
                      </div>
                    </div>
                  </td>
                  <td className={`${tdClass} border-y border-line/80`}>
                    <div className="min-w-[150px]">
                      <div className="text-sm font-semibold text-slate-800">{leads[message.lead_id] || message.lead_id}</div>
                    </div>
                  </td>
                  <td className={`${tdClass} border-y border-line/80`}>
                    <TriggerChip value={message.trigger_keyword} />
                  </td>
                  <td className={`${tdClass} border-y border-line/80`}>
                    <MessageTypeBadge value={message.message_type} />
                  </td>
                  <td className={`${tdClass} border-y border-line/80`}>{message.status === "sent" && message.created_at ? new Date(message.created_at).toLocaleString() : "Not sent"}</td>
                  <td className={`${tdClass} rounded-r-xl border-y border-r border-line/80`}>
                    <div className="grid max-w-[320px] gap-2 text-sm text-slate-700">
                      <RetryMeta message={message} />
                      {canRetryMessages && message.status === "failed" && message.retryable ? (
                        <Button type="button" variant="secondary" disabled={retrying[message.id]} className="h-8 w-fit gap-2 px-3 text-xs" onClick={() => retry(message.id)}>
                          <RefreshCcw className="h-3.5 w-3.5" aria-hidden="true" />
                          Retry
                        </Button>
                      ) : null}
                      <details className="text-xs text-muted">
                        <summary className="cursor-pointer font-semibold text-slate-600">Technical details</summary>
                        <div className="mt-2 grid gap-1 rounded-lg border border-line bg-slate-50 p-2 font-mono">
                          <span>Comment: {message.comment_id || "None"}</span>
                          <span>Campaign: {message.campaign_id}</span>
                          <span>Lead: {message.lead_id}</span>
                        </div>
                      </details>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        ) : null}
      </Panel>
    </div>
  );
}
