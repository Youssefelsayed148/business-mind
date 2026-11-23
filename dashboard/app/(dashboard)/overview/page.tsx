"use client";

import type { ComponentType } from "react";
import { useEffect, useState } from "react";
import { AlertTriangle, MessageSquare, MousePointerClick, UserPlus, Megaphone } from "lucide-react";
import { ActivityFeed } from "@/components/activity/ActivityFeed";
import { DataState } from "@/components/ui/DataState";
import { LiveStatusDot } from "@/components/ui/LiveStatusDot";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { Skeleton } from "@/components/ui/Skeleton";
import { api } from "@/lib/api";
import type { OverviewStats } from "@/lib/types";

const cards = [
  { key: "active_campaigns", label: "Active campaigns", icon: Megaphone },
  { key: "triggers_today", label: "Triggers today", icon: MousePointerClick },
  { key: "messages_sent_today", label: "Messages sent", icon: MessageSquare },
  { key: "failed_messages_today", label: "Failed messages", icon: AlertTriangle },
  { key: "new_leads_today", label: "New leads", icon: UserPlus },
] satisfies Array<{ key: keyof OverviewStats; label: string; icon: ComponentType<{ className?: string }> }>;

export default function OverviewPage() {
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<OverviewStats>("/stats/overview")
      .then(setStats)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load overview"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="grid gap-6">
      <PageHeader title="Overview" description="Monitor campaign activity, delivery health, and lead capture from the existing automation data." />
      <DataState loading={loading} error={error} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {cards.map(({ key, label, icon: Icon }, index) => (
          <Panel key={key} className="relative overflow-hidden">
            <div className={`absolute inset-x-0 top-0 h-1 ${index % 2 === 0 ? "bg-accent" : "bg-teal"}`} />
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <LiveStatusDot tone={key === "failed_messages_today" ? "error" : key === "triggers_today" ? "info" : "success"} />
                  <p className="text-sm font-semibold text-slate-500">{label}</p>
                </div>
                {loading ? <Skeleton className="mt-3 h-9 w-16" /> : <p className="mt-2 text-3xl font-bold text-ink">{stats?.[key] ?? 0}</p>}
              </div>
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-emerald-200 bg-mint text-emerald-700">
                <Icon className="h-5 w-5" aria-hidden="true" />
              </span>
            </div>
          </Panel>
        ))}
      </div>
      <Panel>
        <div className="mb-4">
          <h2 className="text-lg font-bold text-ink">Activity feed</h2>
          <p className="mt-1 text-sm text-muted">Recent automation events from the existing logs stream.</p>
        </div>
        <ActivityFeed />
      </Panel>
    </div>
  );
}
