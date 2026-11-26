"use client";

import Link from "next/link";

import { manyRequest } from "@/lib/many";
import { PageState } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  DataTable,
  LinkButton,
  PageHeader,
  StatusBadge,
} from "@/lib/ui";
import {
  formatDate,
  statusLabel,
  statusTone,
  type WhatsappCampaign,
  type WhatsappTemplate,
} from "@/lib/whatsapp-types";

import { useWhatsapp } from "../whatsapp-shell";

import "@/app/whatsapp-screen.css";

export default function WhatsappCampaignsPage() {
  const { tenantId, account, outreachDisabled } = useWhatsapp();
  const base = `/app/${tenantId}/whatsapp`;
  const { data, status } = useManyData<{
    campaigns: WhatsappCampaign[];
    templates: WhatsappTemplate[];
  }>(
    async () => {
      const scope = { kind: "org", tenantId } as const;
      const [campaigns, templates] = await Promise.all([
        manyRequest<WhatsappCampaign[]>(
          scope,
          "GET",
          `whatsapp/campaigns?account_id=${account.id}`,
        ),
        manyRequest<WhatsappTemplate[]>(
          scope,
          "GET",
          `whatsapp/templates?account_id=${account.id}`,
        ),
      ]);
      return { campaigns, templates };
    },
    account.id,
    {
      isEmpty: (result) => result.campaigns.length === 0,
      emptyMessage:
        "No campaigns yet. Create a campaign to run an audience dry-run before sending.",
    },
  );
  const names = Object.fromEntries(
    (data?.templates ?? []).map((t) => [t.id, t.name]),
  );
  return (
    <>
      <PageHeader
        title="WhatsApp campaigns"
        purpose="Create compliant template campaigns and monitor their delivery lifecycle."
        actions={
          outreachDisabled ? (
            <Button disabled title="Outreach is globally disabled">
              New campaign
            </Button>
          ) : (
            <LinkButton
              href={`${base}/campaigns/new`}
              variant="primary"
              icon="plus"
              data-testid="wa-campaign-new"
            >
              New campaign
            </LinkButton>
          )
        }
      />
      <PageState status={status} homeHref={`/app/${tenantId}`}>
        {data && (
          <DataTable
            data-testid="wa-campaigns-table"
            caption="WhatsApp campaigns"
            rows={data.campaigns}
            rowKey={(row) => row.id}
            columns={[
              {
                key: "name",
                header: "Campaign",
                cell: (row) => (
                  <Link
                    href={`${base}/campaigns/${row.id}`}
                    dir="auto"
                    data-testid={`wa-campaign-${row.id}`}
                  >
                    {row.name}
                  </Link>
                ),
              },
              {
                key: "template",
                header: "Template",
                cell: (row) => (
                  <span dir="auto">
                    {names[row.template_id] || "Unknown template"}
                  </span>
                ),
              },
              {
                key: "status",
                header: "Status",
                cell: (row) => (
                  <StatusBadge value={row.status} tone={statusTone(row.status)}>
                    {statusLabel(row.status)}
                  </StatusBadge>
                ),
              },
              {
                key: "recipients",
                header: "Recipients",
                cell: (row) => row.total_recipients,
              },
              {
                key: "progress",
                header: "Progress",
                cell: (row) =>
                  `${row.sent_count} sent · ${row.failed_count} failed · ${row.skipped_count} skipped`,
              },
              {
                key: "created",
                header: "Created",
                cell: (row) => formatDate(row.created_at),
              },
            ]}
          />
        )}
      </PageState>
    </>
  );
}
