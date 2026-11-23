"use client";

import { useEffect, useMemo, useState } from "react";
import { MetadataBlock } from "@/components/logs/MetadataBlock";
import { Avatar } from "@/components/ui/Avatar";
import { Field, Select } from "@/components/ui/Field";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { FeedSkeleton } from "@/components/ui/Skeleton";
import { Highlight } from "@/components/ui/Highlight";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import { groupLogFlow } from "@/lib/logGrouping";
import type { ActivityLog, Campaign } from "@/lib/types";
import {
  EventIcon,
  eventCategory,
  eventLabel,
  eventSeverity,
  formatExactTime,
  formatRelativeTime,
  severityStyles,
} from "@/lib/eventPresentation";

const KNOWN_EVENT_TYPES = [
  "webhook_received",
  "webhook_processed",
  "campaign_matched",
  "campaign_deleted",
  "message_queued",
  "message_sent",
  "message_failed",
  "account_disconnected",
  "account_connected",
  "account_reconnected",
  "login_failed",
  "login_success",
  "campaign_paused_account_disconnected",
  "activated",
  "created",
  "updated",
  "archived",
  "campaign_created",
  "campaign_updated",
  "campaign_activated",
  "campaign_paused",
  "campaign_archived",
  "campaign_unarchived",
];

type EventTypeOption = {
  label: string;
  value: string;
};

function buildEventTypeOptions(eventTypes: string[]): EventTypeOption[] {
  const byLabel = new Map<string, Set<string>>();
  eventTypes.filter(Boolean).forEach((eventType) => {
    const label = eventLabel(eventType);
    if (!byLabel.has(label)) {
      byLabel.set(label, new Set());
    }
    byLabel.get(label)?.add(eventType);
  });
  return Array.from(byLabel.entries())
    .map(([label, values]) => ({ label, value: Array.from(values).sort().join(",") }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export default function LogsPage() {
  const [logs, setLogs] = useState<ActivityLog[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [availableEventTypes, setAvailableEventTypes] = useState<string[]>(KNOWN_EVENT_TYPES);
  const [filters, setFilters] = useState({ level: "", campaign_id: "", event_type: "", limit: "100" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});

  const query = useMemo(() => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    return params.toString();
  }, [filters]);

  useEffect(() => {
    setLoading(true);
    api.get<ActivityLog[]>(`/logs?${query}`)
      .then((data) => {
        setLogs(data);
        setAvailableEventTypes((current) => {
          const next = new Set([...KNOWN_EVENT_TYPES, ...current, ...data.map((log) => log.event_type).filter(Boolean)]);
          return Array.from(next).sort((a, b) => eventLabel(a).localeCompare(eventLabel(b)));
        });
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load logs"))
      .finally(() => setLoading(false));
  }, [query]);

  useEffect(() => {
    api.get<Campaign[]>("/campaigns").then(setCampaigns).catch(() => setCampaigns([]));
  }, []);

  return (
    <div className="grid gap-6">
      <PageHeader title="Logs" description="Filter automation events and inspect metadata from the existing activity log stream." />
      <Panel className="sticky top-4 z-20 bg-white/95 backdrop-blur">
        <div className="mb-4">
          <h2 className="text-lg font-bold text-ink">Log filters</h2>
          <p className="mt-1 text-sm text-muted">Narrow events by level, campaign, event type, or result limit.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          <Select label="Level" value={filters.level} onChange={(e) => setFilters({ ...filters, level: e.target.value })}>
            <option value="">All levels</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </Select>
          <Select label="Campaign" value={filters.campaign_id} onChange={(e) => setFilters({ ...filters, campaign_id: e.target.value })}>
            <option value="">All campaigns</option>
            {campaigns.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name} ({campaign.status})
              </option>
            ))}
          </Select>
          <Select label="Event type" value={filters.event_type} onChange={(e) => setFilters({ ...filters, event_type: e.target.value })}>
            <option value="">All event types</option>
            {buildEventTypeOptions(availableEventTypes).map((eventType) => (
              <option key={eventType.value} value={eventType.value}>
                {eventType.label}
              </option>
            ))}
          </Select>
          <Field label="Limit" type="number" min={1} max={500} value={filters.limit} onChange={(e) => setFilters({ ...filters, limit: e.target.value })} />
        </div>
      </Panel>
      <Panel>
        <div className="mb-4">
          <h2 className="text-lg font-bold text-ink">Event stream</h2>
          <p className="mt-1 text-sm text-muted">Most recent logs matching the selected filters.</p>
        </div>
        <DataState loading={loading} error={error} />
        {loading ? <FeedSkeleton rows={5} /> : null}
        <div className="relative grid gap-4 before:absolute before:left-[21px] before:top-2 before:h-[calc(100%-1rem)] before:w-px before:bg-slate-200">
          {!loading && !error && logs.length === 0 ? <EmptyState title="No logs found" message="Try adjusting filters or wait for campaign activity." /> : null}
          {groupLogFlow(logs).map((group) => {
            const log = group.logs[0];
            const severity = eventSeverity(log.event_type, log.level);
            const styles = severityStyles[severity];
            const category = eventCategory(log.event_type);
            const expanded = openGroups[group.id];
            const displayTitle = group.kind === "group" ? "Message flow" : eventLabel(log.event_type);
            return (
            <div key={group.id} className={`relative grid gap-4 rounded-xl border border-l-4 border-line bg-white p-4 text-sm shadow-sm shadow-slate-200/60 transition duration-150 hover:border-slate-300 ${styles.border}`}>
              <div className="grid gap-3 md:grid-cols-[44px_1fr_auto]">
                <span className={`z-10 flex h-11 w-11 items-center justify-center rounded-xl border ${styles.iconWrap}`}>
                  <EventIcon eventType={log.event_type} className={`h-5 w-5 ${styles.icon}`} />
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Avatar label={log.campaign || category} size="sm" />
                    <h3 className="font-semibold text-ink"><Highlight text={displayTitle} term={filters.event_type} /></h3>
                    {group.logs.length > 1 ? <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-600">{group.logs.length} events</span> : null}
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-500">{category}</span>
                    <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${styles.badge}`}>{severity}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                    <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-600"><Highlight text={log.event_type} term={filters.event_type} /></code>
                    {log.actor_email ? <span>{log.actor_email}</span> : null}
                    <span>{log.entity_name || log.campaign || "No campaign"}</span>
                    <span>{formatRelativeTime(log.created_at)}</span>
                    <span>{formatExactTime(log.created_at)}</span>
                  </div>
                </div>
                <span className="text-left text-xs font-medium text-muted md:text-right">{group.kind === "group" ? group.id.slice(0, 24) : log.id}</span>
              </div>
              <p className="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-slate-700">{log.message}</p>
              {group.logs.length > 1 ? (
                <button type="button" className="w-fit text-xs font-semibold text-slate-500 hover:text-ink" onClick={() => setOpenGroups({ ...openGroups, [group.id]: !expanded })}>
                  {expanded ? "Collapse grouped events" : "Expand grouped events"}
                </button>
              ) : null}
              {expanded ? (
                <div className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
                  {group.logs.map((child) => (
                    <div key={child.id} className="grid gap-1 rounded-md bg-white p-2">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <EventIcon eventType={child.event_type} className="h-3.5 w-3.5" />
                        <span className="font-semibold text-ink">{eventLabel(child.event_type)}</span>
                        <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-600">{child.event_type}</code>
                        <span className="text-muted">{formatRelativeTime(child.created_at)}</span>
                      </div>
                      <p className="text-xs text-slate-600">{child.message}</p>
                    </div>
                  ))}
                </div>
              ) : null}
              <MetadataBlock metadata={log.metadata} />
            </div>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
