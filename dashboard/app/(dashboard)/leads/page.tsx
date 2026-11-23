"use client";

import { useEffect, useMemo, useState } from "react";
import { LeadFilters } from "@/components/leads/LeadFilters";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { PlatformBadge } from "@/components/ui/PlatformBadge";
import { Highlight } from "@/components/ui/Highlight";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { TableWrap, tableClass, tdClass, thClass, theadRowClass, trClass } from "@/components/ui/Table";
import { api, apiBaseUrl, getCurrentWorkspaceMembership } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import type { Campaign, InstagramAccount, Lead } from "@/lib/types";

function KeywordChip({ keyword, search }: { keyword?: string | null; search?: string }) {
  if (!keyword) {
    return <span className="text-muted">Not available</span>;
  }

  return (
    <span dir="auto" className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700">
      <Highlight text={keyword} term={search} />
    </span>
  );
}

function SourceBadge({ source }: { source?: string | null }) {
  const isCold = source === "cold_dm";
  const label = isCold ? "Cold DM" : "Campaign";
  const cls = isCold
    ? "border-amber-200 bg-amber-50 text-amber-700"
    : "border-slate-200 bg-slate-50 text-slate-700";
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${cls}`}>
      {label}
    </span>
  );
}

function CapturedAt({ value }: { value?: string | null }) {
  return <span className="whitespace-nowrap text-sm font-medium text-slate-700">{value ? new Date(value).toLocaleString() : "Unknown"}</span>;
}

function AccountCell({ username }: { username?: string | null }) {
  return (
    <div className="min-w-[140px]">
      <span className="text-sm font-semibold text-slate-800">{username || "Unknown account"}</span>
    </div>
  );
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [accounts, setAccounts] = useState<InstagramAccount[]>([]);
  const [filters, setFilters] = useState({ campaignId: "", accountId: "", platform: "", search: "" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (filters.campaignId) params.set("campaign_id", filters.campaignId);
    if (filters.accountId) params.set("instagram_account_id", filters.accountId);
    if (filters.search) params.set("search", filters.search);
    return params.toString();
  }, [filters]);

  useEffect(() => {
    api.get<Campaign[]>("/campaigns").then(setCampaigns).catch(() => setCampaigns([]));
    api.get<InstagramAccount[]>("/instagram/accounts").then(setAccounts).catch(() => setAccounts([]));
  }, []);

  useEffect(() => {
    setLoading(true);
    api.get<Lead[]>(`/leads${query ? `?${query}` : ""}`)
      .then(setLeads)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load leads"))
      .finally(() => setLoading(false));
  }, [query]);

  // Platform filtering is client-side (the /leads endpoint returns everything
  // already) — with only two real platforms so far, an extra server round
  // trip isn't worth it yet.
  const visibleLeads = useMemo(
    () => (filters.platform ? leads.filter((lead) => lead.platform === filters.platform) : leads),
    [leads, filters.platform],
  );

  async function exportCsv() {
    const token = getAccessToken();
    const workspace = await getCurrentWorkspaceMembership();
    if (!workspace) {
      setError("Select an accessible workspace before exporting leads.");
      return;
    }
    const response = await fetch(`${apiBaseUrl}/leads/export.csv`, {
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "X-Workspace-Id": workspace.id,
      },
    });
    if (!response.ok) {
      setError("Unable to export leads. Please try again.");
      return;
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "leads.csv";
    link.click();
    window.URL.revokeObjectURL(url);
  }

  return (
    <div className="grid gap-6">
      <PageHeader title="Leads" description="Review leads captured by campaign activity and export the current lead list.">
        <Button type="button" variant="secondary" onClick={exportCsv}>Export CSV</Button>
      </PageHeader>
      <Panel className="sticky top-4 z-20 bg-white/95 backdrop-blur">
        <LeadFilters
          campaigns={campaigns}
          accounts={accounts}
          campaignId={filters.campaignId}
          accountId={filters.accountId}
          platform={filters.platform}
          search={filters.search}
          onChange={setFilters}
        />
      </Panel>
      <Panel>
        <div className="mb-4">
          <h2 className="text-lg font-bold text-ink">Lead records</h2>
          <p className="mt-1 text-sm text-muted">Filter captured leads by platform, campaign, Instagram account, or search term.</p>
        </div>
        <DataState loading={loading} error={error} />
        {loading ? <TableSkeleton rows={5} columns={6} /> : null}
        {!loading && !error && visibleLeads.length === 0 ? <EmptyState title="No leads found" message="Leads will appear here after matching campaign activity." /> : null}
        {visibleLeads.length > 0 ? (
        <TableWrap>
          <table className={`${tableClass} min-w-[900px] border-separate border-spacing-y-2`}>
            <thead>
              <tr className={theadRowClass}>
                <th className={thClass}>Username</th>
                <th className={thClass}>Platform</th>
                <th className={thClass}>Source</th>
                <th className={thClass}>Source Campaign</th>
                <th className={thClass}>Captured Keyword</th>
                <th className={thClass}>Account</th>
                <th className={thClass}>Captured At</th>
              </tr>
            </thead>
            <tbody>
              {visibleLeads.map((lead) => (
                <tr key={lead.id} className={`${trClass} rounded-xl bg-white shadow-sm shadow-slate-200/50 hover:bg-white hover:shadow-md`}>
                  <td className={`${tdClass} rounded-l-xl border-y border-l border-line/80 font-semibold text-ink`}>
                    <div className="min-w-[180px]">
                      <div className="text-sm font-bold text-ink"><Highlight text={lead.username || lead.ig_user_id} term={filters.search} /></div>
                      <div className="mt-1 font-mono text-xs font-medium text-muted">{lead.ig_user_id}</div>
                    </div>
                  </td>
                  <td className={`${tdClass} border-y border-line/80`}>
                    <PlatformBadge platform={lead.platform} />
                  </td>
                  <td className={`${tdClass} border-y border-line/80`}>
                    <SourceBadge source={lead.lead_source} />
                  </td>
                  <td className={`${tdClass} border-y border-line/80`}>
                    <div className="min-w-[170px]">
                      <div className="text-sm font-semibold text-slate-800">
                        {lead.lead_source === "cold_dm"
                          ? "Cold DM"
                          : lead.source_campaign || "Unknown campaign"}
                      </div>
                    </div>
                  </td>
                  <td className={`${tdClass} border-y border-line/80`}><KeywordChip keyword={lead.keyword} search={filters.search} /></td>
                  <td className={`${tdClass} border-y border-line/80`}>
                    <AccountCell
                      username={lead.instagram_account_username || lead.whatsapp_account_username || lead.facebook_page_username}
                    />
                  </td>
                  <td className={`${tdClass} rounded-r-xl border-y border-r border-line/80`}>
                    <CapturedAt value={lead.captured_at || lead.first_seen} />
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
