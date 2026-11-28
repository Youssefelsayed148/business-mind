"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { FacebookCampaignForm } from "@/lib/many-facebook/campaign-form";
import type { CampaignPage, FacebookCampaign } from "@/lib/many-facebook/types";
import { manyRequest, type ManyScope } from "@/lib/many";
import { orgRoleSatisfies } from "@/lib/org-role";
import { PageState } from "@/lib/page-state";
import {
  Button,
  ConfirmAction,
  DataTable,
  Empty,
  Notice,
  PageHeader,
  StatusBadge,
} from "@/lib/ui";
import { useManyData } from "@/lib/use-many";
import { useOrgRole } from "@/lib/use-org-role";

import "@/app/channels-screen-many.css";

interface CampaignData {
  campaigns: FacebookCampaign[];
  pages: CampaignPage[];
}

/**
 * Facebook comment-to-message campaigns of one organization, through the SaaS proxy.
 * Everyone reads. Manager and above create, edit, pause and manage keywords
 * (campaigns.manage); Admin and above delete (campaigns.run).
 */
export default function FacebookCampaignsPage() {
  const params = useParams<{ tenant: string }>();
  const tenantId = params.tenant;
  const scope = useMemo<ManyScope>(
    () => ({ kind: "org", tenantId }),
    [tenantId],
  );
  const { role } = useOrgRole(tenantId);
  const canManage = orgRoleSatisfies(role, "manager");
  const canDelete = orgRoleSatisfies(role, "admin");
  const [form, setForm] = useState<{
    campaign: FacebookCampaign | null;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data, status, reload } = useManyData<CampaignData>(async () => {
    const [campaigns, pages] = await Promise.all([
      manyRequest<FacebookCampaign[]>(scope, "GET", "facebook/campaigns"),
      manyRequest<CampaignPage[]>(scope, "GET", "facebook/accounts"),
    ]);
    return { campaigns, pages };
  }, tenantId);

  function pageName(id: string | number): string {
    const page = data?.pages.find((row) => String(row.id) === String(id));
    return page?.page_name || page?.page_id || "Unknown Page";
  }

  async function toggleStatus(campaign: FacebookCampaign) {
    setError(null);
    try {
      await manyRequest(
        scope,
        "PATCH",
        `facebook/campaigns/${encodeURIComponent(String(campaign.id))}`,
        { status: campaign.status === "active" ? "paused" : "active" },
      );
      reload();
    } catch (caught) {
      setError(
        caught instanceof Error && caught.message
          ? caught.message
          : "Could not change the campaign status.",
      );
    }
  }

  async function remove(campaign: FacebookCampaign) {
    setError(null);
    try {
      await manyRequest(
        scope,
        "DELETE",
        `facebook/campaigns/${encodeURIComponent(String(campaign.id))}`,
      );
      reload();
    } catch (caught) {
      setError(
        caught instanceof Error && caught.message
          ? caught.message
          : "Could not delete the campaign.",
      );
    }
  }

  const hasPages = (data?.pages.length ?? 0) > 0;

  return (
    <>
      <PageHeader
        title="Facebook campaigns"
        purpose="Comment-to-message campaigns for connected Facebook Pages."
        actions={
          canManage && hasPages ? (
            <Button
              data-testid="new-campaign"
              onClick={() => setForm({ campaign: null })}
            >
              New campaign
            </Button>
          ) : undefined
        }
      />
      {error && (
        <div data-testid="campaigns-error">
          <Notice message={error} tone="error" scope="item" />
        </div>
      )}
      <PageState status={status} homeHref={`/app/${tenantId}`}>
        {data && (
          <div className="mf-page" data-testid="campaigns-page">
            {!hasPages && (
              <div data-testid="campaigns-no-pages">
                <Empty>
                  No Facebook Pages connected yet. Connect one on the Channels
                  page before creating a campaign.
                </Empty>
                <p>
                  <Link href={`/app/${tenantId}/channels`}>Go to Channels</Link>
                </p>
              </div>
            )}

            {form && canManage && hasPages && (
              <FacebookCampaignForm
                key={form.campaign ? String(form.campaign.id) : "new"}
                scope={scope}
                pages={data.pages}
                campaign={form.campaign}
                onCancel={() => setForm(null)}
                onKeywordsChanged={reload}
                onSaved={() => {
                  setForm(null);
                  reload();
                }}
              />
            )}

            {hasPages && (
              <DataTable
                caption="Facebook campaigns"
                rows={data.campaigns}
                rowKey={(row) => String(row.id)}
                empty={
                  <div data-testid="campaigns-empty">
                    <Empty>
                      No campaigns yet.
                      {canManage
                        ? " Create one to start replying to matching comments."
                        : ""}
                    </Empty>
                  </div>
                }
                columns={[
                  {
                    key: "name",
                    header: "Name",
                    cell: (row) => <span dir="auto">{row.name}</span>,
                  },
                  {
                    key: "page",
                    header: "Page",
                    cell: (row) => (
                      <span dir="auto">{pageName(row.facebook_page_id)}</span>
                    ),
                  },
                  {
                    key: "keywords",
                    header: "Keywords",
                    cell: (row) => (
                      <span className="mf-keywords-inline">
                        {row.keywords.map((keyword) => (
                          <span
                            key={String(keyword.id)}
                            className="channel-badge"
                            dir="auto"
                          >
                            {keyword.normalized_keyword}
                          </span>
                        ))}
                      </span>
                    ),
                  },
                  {
                    key: "status",
                    header: "Status",
                    cell: (row) =>
                      canManage ? (
                        <button
                          type="button"
                          className="quiet-button"
                          data-testid={`toggle-status-${row.id}`}
                          aria-label={`${row.status === "active" ? "Pause" : "Activate"} ${row.name}`}
                          onClick={() => void toggleStatus(row)}
                        >
                          <StatusBadge value={row.status} />
                        </button>
                      ) : (
                        <StatusBadge value={row.status} />
                      ),
                  },
                  {
                    key: "triggers",
                    header: "Triggers",
                    cell: (row) => row.total_triggers,
                  },
                  {
                    key: "actions",
                    header: "Actions",
                    cell: (row) => (
                      <span className="mf-row-actions">
                        {canManage && (
                          <Button
                            variant="quiet"
                            data-testid={`edit-${row.id}`}
                            onClick={() => setForm({ campaign: row })}
                          >
                            Edit
                          </Button>
                        )}
                        {canDelete && (
                          <ConfirmAction
                            testId={`delete-${row.id}`}
                            title={`Delete ${row.name}?`}
                            description="The campaign and its keywords are removed. This cannot be undone."
                            confirmLabel="Delete campaign"
                            onConfirm={() => void remove(row)}
                          >
                            Delete
                          </ConfirmAction>
                        )}
                      </span>
                    ),
                  },
                ]}
              />
            )}
          </div>
        )}
      </PageState>
    </>
  );
}
