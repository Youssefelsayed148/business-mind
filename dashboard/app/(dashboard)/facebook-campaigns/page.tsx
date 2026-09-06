"use client";

import { useEffect, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { FacebookCampaignForm } from "@/components/campaigns/FacebookCampaignForm";
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
import type { FacebookCampaign, FacebookPage } from "@/lib/types";

export default function FacebookCampaignsPage() {
  const [campaigns, setCampaigns] = useState<FacebookCampaign[]>([]);
  const [pages, setPages] = useState<FacebookPage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<FacebookCampaign | null>(null);

  const canManage = useCan("manage_campaigns");
  const canDelete = useCan("delete_campaigns");
  const toast = useToast();

  function load() {
    setLoading(true);
    Promise.all([
      api.get<FacebookCampaign[]>("/facebook/campaigns"),
      api.get<FacebookPage[]>("/facebook/accounts"),
    ])
      .then(([campaignData, pageData]) => {
        setCampaigns(campaignData);
        setPages(pageData);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load campaigns"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  function pageName(id: string): string {
    const page = pages.find((p) => String(p.id) === String(id));
    return page?.page_name || page?.page_id || "Unknown Page";
  }

  async function toggleStatus(campaign: FacebookCampaign) {
    const nextStatus = campaign.status === "active" ? "paused" : "active";
    try {
      await api.patch(`/facebook/campaigns/${campaign.id}`, { status: nextStatus });
      toast.success(nextStatus === "active" ? "Campaign activated." : "Campaign paused.");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update campaign status");
    }
  }

  async function remove(campaignId: string) {
    try {
      await api.delete(`/facebook/campaigns/${campaignId}`);
      toast.success("Campaign deleted.");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete campaign");
    }
  }

  return (
    <div className="grid gap-6">
      <PageHeader title="Facebook Campaigns" description="Comment-to-DM campaigns for connected Facebook Pages.">
        {canManage && pages.length > 0 ? (
          <Button
            type="button"
            className="gap-2"
            onClick={() => {
              setEditing(null);
              setShowForm(true);
            }}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            New campaign
          </Button>
        ) : null}
      </PageHeader>

      {pages.length === 0 && !loading ? (
        <EmptyState
          title="No Facebook Pages connected"
          message="Connect a Facebook Page from the Accounts page before creating a campaign."
        />
      ) : null}

      {showForm ? (
        <FacebookCampaignForm
          pages={pages}
          campaign={editing}
          onCancel={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false);
            load();
          }}
        />
      ) : null}

      <Panel>
        <DataState loading={loading} error={error} />
        {loading ? <TableSkeleton rows={4} columns={6} /> : null}
        {!loading && !error && campaigns.length === 0 ? (
          <EmptyState title="No campaigns yet" message="Create a campaign to start replying to matching comments." />
        ) : null}
        {campaigns.length > 0 ? (
          <TableWrap>
            <table className={`${tableClass} min-w-[860px]`}>
              <thead>
                <tr className={theadRowClass}>
                  <th className={thClass}>Name</th>
                  <th className={thClass}>Page</th>
                  <th className={thClass}>Keywords</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Triggers</th>
                  <th className={thClass}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((campaign) => (
                  <tr key={campaign.id} className={trClass}>
                    <td className={`${tdClass} font-semibold text-ink`}>{campaign.name}</td>
                    <td className={tdClass}>{pageName(String(campaign.facebook_page_id))}</td>
                    <td className={tdClass}>
                      <div className="flex flex-wrap gap-1">
                        {campaign.keywords.map((kw) => (
                          <span
                            key={kw.id}
                            className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-700"
                          >
                            {kw.normalized_keyword}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className={tdClass}>
                      <button type="button" onClick={() => canManage && toggleStatus(campaign)} disabled={!canManage}>
                        <Badge value={campaign.status} />
                      </button>
                    </td>
                    <td className={tdClass}>{campaign.total_triggers}</td>
                    <td className={`${tdClass} flex flex-wrap gap-2`}>
                      {canManage ? (
                        <Button
                          type="button"
                          variant="secondary"
                          onClick={() => {
                            setEditing(campaign);
                            setShowForm(true);
                          }}
                        >
                          <Pencil className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      ) : null}
                      {canDelete ? (
                        <Button type="button" variant="danger" onClick={() => remove(String(campaign.id))}>
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      ) : null}
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
