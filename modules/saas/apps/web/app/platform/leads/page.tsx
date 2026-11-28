"use client";

import { useState } from "react";

import { manyRequest } from "@/lib/many";
import { PageState, type PageStatus } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import { Card, DataTable, Field, PageHeader, StatusBadge } from "@/lib/ui";
import {
  filterLeadsByPlatform,
  leadAccountName,
  leadCampaignLabel,
  leadSourceLabel,
  leadsQuery,
  NO_LEAD_FILTERS,
} from "@/lib/many-staff/leads";
import { Pager } from "@/lib/many-staff/pager";
import { paginate } from "@/lib/many-staff/paging";
import type { ManyLead } from "@/lib/many-staff/types";
import { useDebounced } from "@/lib/many-staff/use-debounced";
import {
  useStaffCampaigns,
  useStaffInstagramAccounts,
} from "@/lib/many-staff/use-lookups";

import "@/app/staff-many-screen.css";

const PLATFORMS = [
  ["", "All platforms"],
  ["instagram", "Instagram"],
  ["whatsapp", "WhatsApp"],
  ["facebook", "Facebook"],
] as const;

/** Leads captured by campaign activity, across all workspaces (platform staff only). */
export default function StaffLeadsPage() {
  const campaigns = useStaffCampaigns();
  const accounts = useStaffInstagramAccounts();
  const [filters, setFilters] = useState(NO_LEAD_FILTERS);
  const [page, setPage] = useState(1);
  const search = useDebounced(filters.search);
  const query = leadsQuery({ ...filters, search });

  const { data, status } = useManyData<ManyLead[]>(
    () =>
      manyRequest<ManyLead[]>(
        { kind: "staff" },
        "GET",
        `leads${query ? `?${query}` : ""}`,
      ),
    query,
  );

  function change(next: Partial<typeof filters>) {
    setFilters((current) => ({ ...current, ...next }));
    setPage(1);
  }

  const visible = filterLeadsByPlatform(data ?? [], filters.platform);
  const paged = paginate(visible, page);
  let shown: PageStatus = status;
  if (status.kind === "ready" && visible.length === 0) {
    shown = {
      kind: "empty",
      message: "No leads found. Leads appear after matching campaign activity.",
    };
  }

  return (
    <div className="staff-many-page">
      <PageHeader
        title="Leads"
        purpose="Leads captured by campaign activity. Platform staff only."
      />
      <Card title="Filters">
        <div className="staff-many-filter-grid">
          <Field label="Platform">
            {(control) => (
              <select
                {...control}
                value={filters.platform}
                onChange={(event) => change({ platform: event.target.value })}
              >
                {PLATFORMS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Campaign">
            {(control) => (
              <select
                {...control}
                value={filters.campaignId}
                onChange={(event) => change({ campaignId: event.target.value })}
              >
                <option value="">All campaigns</option>
                {campaigns.map((campaign) => (
                  <option key={campaign.id} value={campaign.id}>
                    {campaign.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Instagram account">
            {(control) => (
              <select
                {...control}
                value={filters.accountId}
                onChange={(event) => change({ accountId: event.target.value })}
              >
                <option value="">All accounts</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.username || account.ig_user_id}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Search username">
            {(control) => (
              <input
                {...control}
                type="search"
                dir="auto"
                value={filters.search}
                onChange={(event) => change({ search: event.target.value })}
              />
            )}
          </Field>
        </div>
      </Card>
      <PageState status={shown} homeHref="/platform">
        <Card title="Lead records">
          <DataTable
            data-testid="staff-leads"
            caption="Leads"
            rows={paged.rows}
            rowKey={(lead) => lead.id}
            columns={[
              {
                key: "username",
                header: "Username",
                cell: (lead) => (
                  <>
                    <strong dir="auto">
                      {lead.username || lead.ig_user_id}
                    </strong>
                    <div className="muted staff-many-id" dir="ltr">
                      {lead.ig_user_id}
                    </div>
                  </>
                ),
              },
              {
                key: "platform",
                header: "Platform",
                cell: (lead) => (
                  <StatusBadge value={lead.platform || "unknown"} tone="info" />
                ),
              },
              {
                key: "source",
                header: "Source",
                cell: (lead) => (
                  <StatusBadge
                    value={lead.lead_source || "campaign"}
                    tone={
                      lead.lead_source === "cold_dm" ? "warning" : "neutral"
                    }
                  >
                    {leadSourceLabel(lead.lead_source)}
                  </StatusBadge>
                ),
              },
              {
                key: "campaign",
                header: "Source campaign",
                cell: (lead) => (
                  <span dir="auto">{leadCampaignLabel(lead)}</span>
                ),
              },
              {
                key: "keyword",
                header: "Captured keyword",
                cell: (lead) =>
                  lead.keyword ? (
                    <code dir="auto">{lead.keyword}</code>
                  ) : (
                    <span className="muted">Not available</span>
                  ),
              },
              {
                key: "account",
                header: "Account",
                cell: (lead) => <span dir="auto">{leadAccountName(lead)}</span>,
              },
              {
                key: "captured",
                header: "Captured at",
                cell: (lead) => {
                  const at = lead.captured_at || lead.first_seen;
                  return at ? new Date(at).toLocaleString() : "Unknown";
                },
              },
            ]}
          />
          <Pager paged={paged} onPage={setPage} noun="Leads" />
        </Card>
      </PageState>
    </div>
  );
}
