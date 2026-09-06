"use client";

import { useEffect, useState } from "react";
import { Bot, UserCheck } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { PlatformBadge } from "@/components/ui/PlatformBadge";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { TableWrap, tableClass, tdClass, thClass, theadRowClass, trClass } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { useCan } from "@/lib/permissions";
import { useToast } from "@/components/ToastProvider";
import type { Conversation, ConversationDetail } from "@/lib/types";

const STATUS_FILTERS = ["all", "bot_active", "handed_off", "closed"] as const;
const PLATFORM_FILTERS = ["all", "instagram", "whatsapp", "facebook"] as const;

function SourceBadge({ source }: { source?: string | null }) {
  const isCold = source === "cold_dm";
  const cls = isCold
    ? "border-amber-200 bg-amber-50 text-amber-700"
    : "border-slate-200 bg-slate-50 text-slate-700";
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${cls}`}>
      {isCold ? "Cold DM" : "Campaign"}
    </span>
  );
}

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionPending, setActionPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>("all");
  const [platformFilter, setPlatformFilter] = useState<(typeof PLATFORM_FILTERS)[number]>("all");
  const canManage = useCan("manage_accounts");
  const toast = useToast();

  async function load() {
    setLoading(true);
    try {
      const data = await api.get<Conversation[]>("/conversations");
      setConversations(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load conversations");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function openThread(id: string) {
    setDetailLoading(true);
    try {
      const detail = await api.get<ConversationDetail>(`/conversations/${id}`);
      setSelected(detail);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load conversation");
    } finally {
      setDetailLoading(false);
    }
  }

  async function takeOver(id: string) {
    setActionPending(true);
    try {
      await api.post(`/conversations/${id}/take-over`);
      toast.success("Bot paused. You've taken over this conversation.");
      await Promise.all([load(), openThread(id)]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to take over conversation");
    } finally {
      setActionPending(false);
    }
  }

  async function resumeBot(id: string) {
    setActionPending(true);
    try {
      await api.post(`/conversations/${id}/resume-bot`);
      toast.success("Bot resumed for this conversation.");
      await Promise.all([load(), openThread(id)]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to resume bot");
    } finally {
      setActionPending(false);
    }
  }

  const filtered = conversations
    .filter((c) => statusFilter === "all" || c.status === statusFilter)
    .filter((c) => platformFilter === "all" || c.platform === platformFilter);

  return (
    <div className="grid gap-6">
      <PageHeader title="Conversations" description="Monitor and, when needed, take over AI-assisted DM conversations." />

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Panel>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-ink">Active threads</h2>
              <p className="mt-1 text-sm text-muted">Leads currently in an AI-continued DM conversation.</p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex gap-1.5">
                {PLATFORM_FILTERS.map((platform) => (
                  <button
                    key={platform}
                    type="button"
                    onClick={() => setPlatformFilter(platform)}
                    className={`rounded-full border px-3 py-1 text-xs font-semibold capitalize transition ${platformFilter === platform ? "border-accent bg-accent text-white" : "border-line bg-white text-slate-600 hover:border-slate-300"}`}
                  >
                    {platform === "all" ? "All platforms" : platform}
                  </button>
                ))}
              </div>
              <div className="flex gap-1.5">
                {STATUS_FILTERS.map((status) => (
                  <button
                    key={status}
                    type="button"
                    onClick={() => setStatusFilter(status)}
                    className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${statusFilter === status ? "border-accent bg-accent text-white" : "border-line bg-white text-slate-600 hover:border-slate-300"}`}
                  >
                    {status === "all" ? "All" : status.replaceAll("_", " ")}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <DataState loading={loading} error={error} />
          {loading ? <TableSkeleton rows={5} columns={5} /> : null}
          {!loading && !error && filtered.length === 0 ? (
            <EmptyState title="No conversations yet" message="Conversations appear once a lead replies after an AI-enabled campaign message." />
          ) : null}
          {filtered.length > 0 ? (
            <TableWrap>
              <table className={`${tableClass} min-w-[820px] border-separate border-spacing-y-2`}>
                <thead>
                  <tr className={theadRowClass}>
                    <th className={thClass}>Status</th>
                    <th className={thClass}>Lead</th>
                    <th className={thClass}>Platform</th>
                    <th className={thClass}>Source</th>
                    <th className={thClass}>Campaign</th>
                    <th className={thClass}>Turns</th>
                    <th className={thClass}>Last activity</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((conversation) => (
                    <tr
                      key={conversation.id}
                      onClick={() => openThread(conversation.id)}
                      className={`${trClass} cursor-pointer rounded-xl bg-white shadow-sm shadow-slate-200/50 hover:bg-slate-50 hover:shadow-md ${selected?.id === conversation.id ? "ring-2 ring-accent/40" : ""}`}
                    >
                      <td className={`${tdClass} rounded-l-xl border-y border-l border-line/80`}>
                        <Badge value={conversation.status} />
                      </td>
                      <td className={`${tdClass} border-y border-line/80 font-semibold text-ink`}>
                        {conversation.lead_username || conversation.lead_id}
                      </td>
                      <td className={`${tdClass} border-y border-line/80`}>
                        <PlatformBadge platform={conversation.platform} />
                      </td>
                      <td className={`${tdClass} border-y border-line/80`}>
                        <SourceBadge source={conversation.lead_source} />
                      </td>
                      <td className={`${tdClass} border-y border-line/80`}>
                        {conversation.campaign_name || conversation.campaign_id || "Direct DM"}
                      </td>
                      <td className={`${tdClass} border-y border-line/80`}>{conversation.turn_count}</td>
                      <td className={`${tdClass} rounded-r-xl border-y border-r border-line/80 text-sm text-muted`}>
                        {conversation.last_message_at ? new Date(conversation.last_message_at).toLocaleString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          ) : null}
        </Panel>

        <Panel className="h-fit">
          <div className="mb-4">
            <h2 className="text-lg font-bold text-ink">Thread</h2>
            <p className="mt-1 text-sm text-muted">Select a conversation to view the full back-and-forth.</p>
          </div>

          {detailLoading ? <TableSkeleton rows={4} columns={1} /> : null}

          {!detailLoading && !selected ? (
            <EmptyState title="No conversation selected" message="Click a row on the left to open its thread." />
          ) : null}

          {!detailLoading && selected ? (
            <div className="grid gap-4">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/70 pb-3">
                <div>
                  <div className="text-sm font-bold text-ink">{selected.lead_username || selected.lead_id}</div>
                  <div className="text-xs text-muted">{selected.campaign_name}</div>
                </div>
                <Badge value={selected.status} />
              </div>

              <div className="grid max-h-[420px] gap-2 overflow-y-auto pr-1">
                {selected.messages.length === 0 ? (
                  <p className="text-sm text-muted">No messages yet.</p>
                ) : (
                  selected.messages.map((message) => (
                    <div
                      key={message.id}
                      className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${message.direction === "inbound" ? "self-start bg-slate-100 text-ink" : "self-end ml-auto bg-accent/10 text-ink"}`}
                    >
                      <p className="whitespace-pre-wrap">{message.content}</p>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                        {message.created_at ? new Date(message.created_at).toLocaleTimeString() : ""}
                        {message.status === "failed" ? <span className="font-semibold text-danger">Failed to send</span> : null}
                      </div>
                    </div>
                  ))
                )}
              </div>

              {canManage ? (
                <div className="flex gap-2 border-t border-line/70 pt-3">
                  {selected.status === "bot_active" ? (
                    <Button type="button" variant="secondary" disabled={actionPending} className="gap-2" onClick={() => takeOver(selected.id)}>
                      <UserCheck className="h-3.5 w-3.5" aria-hidden="true" />
                      Take over
                    </Button>
                  ) : (
                    <Button type="button" variant="secondary" disabled={actionPending} className="gap-2" onClick={() => resumeBot(selected.id)}>
                      <Bot className="h-3.5 w-3.5" aria-hidden="true" />
                      Resume bot
                    </Button>
                  )}
                </div>
              ) : null}
            </div>
          ) : null}
        </Panel>
      </div>
    </div>
  );
}
