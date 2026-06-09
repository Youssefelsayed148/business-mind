"use client";

import { useEffect, useState } from "react";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Avatar } from "@/components/ui/Avatar";
import { FeedSkeleton } from "@/components/ui/Skeleton";
import { LiveStatusDot } from "@/components/ui/LiveStatusDot";
import type { ActivityLog } from "@/lib/types";
import { api } from "@/lib/api";
import { groupLogFlow } from "@/lib/logGrouping";
import {
  EventIcon,
  eventCategory,
  eventLabel,
  eventSeverity,
  formatExactTime,
  formatRelativeTime,
  severityStyles,
} from "@/lib/eventPresentation";

export function ActivityFeed() {
  const [logs, setLogs] = useState<ActivityLog[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const data = await api.get<ActivityLog[]>("/logs?limit=20");
        if (active) {
          setLogs(data);
          setError(null);
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Failed to load activity");
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    const interval = window.setInterval(load, 5000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  return (
    <div className="grid gap-3">
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-500">
        <LiveStatusDot tone="info" label="Live activity polling" />
        Live activity
      </div>
      <DataState loading={loading} error={error} />
      {loading ? <FeedSkeleton rows={4} /> : null}
      {!loading && !error && logs.length === 0 ? <EmptyState title="No activity yet" /> : null}
      <div className="relative grid gap-4 before:absolute before:left-5 before:top-2 before:h-[calc(100%-1rem)] before:w-px before:bg-slate-200">
      {groupLogFlow(logs).map((group) => {
        const log = group.logs[0];
        const severity = eventSeverity(log.event_type, log.level);
        const styles = severityStyles[severity];
        const category = eventCategory(log.event_type);
        const expanded = openGroups[group.id];
        const displayTitle = group.kind === "group" ? group.title : eventLabel(log.event_type);
        return (
          <div key={group.id} className={`relative grid grid-cols-[40px_1fr] gap-3 rounded-xl border border-l-4 border-line/80 bg-white p-3 shadow-sm shadow-slate-200/60 transition duration-150 hover:border-slate-300 hover:bg-slate-50/60 ${styles.border}`}>
            <span className={`z-10 flex h-10 w-10 items-center justify-center rounded-lg border ${styles.iconWrap}`}>
              <EventIcon eventType={log.event_type} className={`h-5 w-5 ${styles.icon}`} />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-ink">{displayTitle}</span>
                {group.logs.length > 1 ? <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-600">{group.logs.length} events</span> : null}
                <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-500">{category}</span>
                <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${styles.badge}`}>{severity}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <Avatar label={log.campaign || category} size="sm" />
                {log.campaign ? <span className="font-medium text-slate-600">{log.campaign}</span> : null}
                <span>{formatRelativeTime(log.created_at)}</span>
                <span>{formatExactTime(log.created_at)}</span>
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-700">{log.message}</p>
              {group.logs.length > 1 ? (
                <button type="button" className="mt-2 text-xs font-semibold text-slate-500 hover:text-ink" onClick={() => setOpenGroups({ ...openGroups, [group.id]: !expanded })}>
                  {expanded ? "Hide flow events" : "Show flow events"}
                </button>
              ) : null}
              {expanded ? (
                <div className="mt-3 grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2">
                  {group.logs.map((child) => (
                    <div key={child.id} className="flex items-center gap-2 text-xs text-slate-600">
                      <EventIcon eventType={child.event_type} className="h-3.5 w-3.5" />
                      <span className="font-semibold text-ink">{eventLabel(child.event_type)}</span>
                      <span>{formatRelativeTime(child.created_at)}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        );
      })}
      </div>
    </div>
  );
}
