"use client";

import { useCallback, useEffect, useState } from "react";

import {
  manyFailureKind,
  manyStaff,
  type ManyFailure,
  type ManyOverview,
} from "@/lib/many";
import { PageState, type PageStatus } from "@/lib/page-state";
import { PageHeader, StatCard } from "@/lib/ui";

import "@/app/overview-screen.css";

const TILES: { key: keyof ManyOverview; label: string }[] = [
  { key: "active_campaigns", label: "Active campaigns" },
  { key: "triggers_today", label: "Triggers today" },
  { key: "messages_sent_today", label: "Messages sent today" },
  { key: "failed_messages_today", label: "Failed messages today" },
  { key: "new_leads_today", label: "New leads today" },
];

/**
 * Many overview for platform staff (Phase 4B, the first page that reads Many through the
 * SaaS proxy). The /platform layout already refuses non-staff on the server; the proxy
 * and Many check the caller again.
 */
export default function ManyOverviewPage() {
  const [data, setData] = useState<ManyOverview | null>(null);
  const [failure, setFailure] = useState<ManyFailure | null>(null);

  const load = useCallback(async () => {
    setFailure(null);
    setData(null);
    try {
      setData(await manyStaff<ManyOverview>("stats/overview"));
    } catch (caught) {
      setFailure(manyFailureKind(caught));
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  const status: PageStatus = failure
    ? { kind: "failed", failure, onRetry: () => void load() }
    : data
      ? { kind: "ready" }
      : { kind: "loading" };

  return (
    <>
      <PageHeader
        title="Many overview"
        purpose="Today's activity across the Many channel service. Platform staff only."
      />
      <PageState status={status} homeHref="/platform">
        {data && (
          <div className="overview-kpis" data-testid="many-overview">
            {TILES.map((tile) => (
              <StatCard
                key={tile.key}
                label={tile.label}
                value={data[tile.key]}
              />
            ))}
          </div>
        )}
      </PageState>
    </>
  );
}
