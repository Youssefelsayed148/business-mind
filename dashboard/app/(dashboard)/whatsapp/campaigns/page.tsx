"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { useWhatsapp } from "@/components/whatsapp/WhatsappShell";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import {
  TableWrap,
  tableClass,
  theadRowClass,
  thClass,
  trClass,
  tdClass,
} from "@/components/ui/Table";
import { api } from "@/lib/api";
import {
  formatDate,
  type WhatsappCampaign,
  type WhatsappTemplate,
} from "@/lib/whatsapp";
import { useWorkspaceCan } from "@/lib/workspacePermissions";
export default function CampaignsPage() {
  const { account, outreachDisabled } = useWhatsapp();
  const canRun = useWorkspaceCan("run_campaigns");
  const [rows, setRows] = useState<WhatsappCampaign[]>([]);
  const [templates, setTemplates] = useState<WhatsappTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get<WhatsappCampaign[]>(
        `/whatsapp/campaigns?account_id=${account!.id}`,
      ),
      api.get<WhatsappTemplate[]>(
        `/whatsapp/templates?account_id=${account!.id}`,
      ),
    ])
      .then(([c, t]) => {
        setRows(c);
        setTemplates(t);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Could not load campaigns"),
      )
      .finally(() => setLoading(false));
  }, [account]);
  const names = Object.fromEntries(templates.map((t) => [t.id, t.name]));
  return (
    <div className="grid gap-6">
      <PageHeader
        title="WhatsApp campaigns"
        description="Create compliant template campaigns and monitor their delivery lifecycle."
      >
        {canRun ? (
          <Link href="/whatsapp/campaigns/new">
            <Button
              className="gap-2"
              disabled={outreachDisabled}
              title={
                outreachDisabled ? "Outreach is globally disabled" : undefined
              }
            >
              <Plus className="h-4 w-4" />
              New campaign
            </Button>
          </Link>
        ) : null}
      </PageHeader>
      <Panel>
        <DataState loading={loading} error={error} />
        {!loading && !error && !rows.length ? (
          <EmptyState
            title="No campaigns"
            message="Create a campaign to run an audience dry-run before sending."
          />
        ) : null}
        {rows.length ? (
          <TableWrap>
            <table className={tableClass}>
              <thead>
                <tr className={theadRowClass}>
                  <th className={thClass}>Campaign</th>
                  <th className={thClass}>Template</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Recipients</th>
                  <th className={thClass}>Progress</th>
                  <th className={thClass}>Created</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} className={trClass}>
                    <td className={tdClass}>
                      <Link
                        href={`/whatsapp/campaigns/${c.id}`}
                        className="font-bold text-emerald-700 hover:underline"
                        dir="auto"
                      >
                        {c.name}
                      </Link>
                    </td>
                    <td className={tdClass} dir="auto">
                      {names[c.template_id] || "Unknown template"}
                    </td>
                    <td className={tdClass}>
                      <Badge value={c.status} />
                    </td>
                    <td className={tdClass}>{c.total_recipients}</td>
                    <td className={tdClass}>
                      {c.sent_count} sent · {c.failed_count} failed ·{" "}
                      {c.skipped_count} skipped
                    </td>
                    <td className={tdClass}>{formatDate(c.created_at)}</td>
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
