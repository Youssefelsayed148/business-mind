"use client";

import { useEffect, useState } from "react";

import { ManyError, manyRequest } from "@/lib/many";
import { PageState, type PageStatus } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  Card,
  DataTable,
  Notice,
  PageHeader,
  StatusBadge,
  Toast,
} from "@/lib/ui";
import {
  campaignLabel,
  canRetry,
  hasCampaign,
  messageTypeLabel,
  retriesLabel,
} from "@/lib/many-staff/messages";
import { Pager } from "@/lib/many-staff/pager";
import { paginate } from "@/lib/many-staff/paging";
import type {
  ManyCampaign,
  ManyLead,
  ManyMessage,
} from "@/lib/many-staff/types";

import "@/app/staff-many-screen.css";

const STAFF = { kind: "staff" } as const;

/** Names for campaign and lead ids; a failure leaves the ids as they are (like the old page). */
function useNames() {
  const [campaigns, setCampaigns] = useState<Record<string, string>>({});
  const [leads, setLeads] = useState<Record<string, string>>({});
  useEffect(() => {
    let cancelled = false;
    manyRequest<ManyCampaign[]>(STAFF, "GET", "campaigns").then(
      (rows) => {
        if (!cancelled)
          setCampaigns(Object.fromEntries(rows.map((c) => [c.id, c.name])));
      },
      () => undefined,
    );
    manyRequest<ManyLead[]>(STAFF, "GET", "leads").then(
      (rows) => {
        if (!cancelled)
          setLeads(
            Object.fromEntries(
              rows.map((l) => [l.id, l.username || l.ig_user_id]),
            ),
          );
      },
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, []);
  return { campaigns, leads };
}

/** Delivery records for campaign messages, with retry of a failed one (platform staff only). */
export default function StaffMessagesPage() {
  const { campaigns, leads } = useNames();
  const [page, setPage] = useState(1);
  const [retrying, setRetrying] = useState<Record<string, boolean>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const { data, status, reload } = useManyData<ManyMessage[]>(
    () => manyRequest<ManyMessage[]>(STAFF, "GET", "messages"),
    "messages",
    {
      isEmpty: (rows) => rows.length === 0,
      emptyMessage:
        "No messages yet. Delivery records appear after campaign triggers.",
    },
  );

  async function retry(id: string) {
    setActionError(null);
    setRetrying((current) => ({ ...current, [id]: true }));
    try {
      await manyRequest(
        STAFF,
        "POST",
        `messages/${encodeURIComponent(id)}/retry`,
      );
      setToast("Message retry queued.");
      reload();
    } catch (caught) {
      setActionError(
        caught instanceof ManyError
          ? caught.message
          : "The message could not be retried.",
      );
    } finally {
      setRetrying((current) => {
        const copy = { ...current };
        delete copy[id];
        return copy;
      });
    }
  }

  const paged = paginate(data ?? [], page);
  const shown: PageStatus = status;

  return (
    <div className="staff-many-page">
      <PageHeader
        title="Messages"
        purpose="Delivery records for campaign messages. Retry a failed message when Many allows it. Platform staff only."
      />
      {actionError && (
        <Notice message={actionError} tone="error" scope="item" />
      )}
      <PageState status={shown} homeHref="/platform">
        <Card title="Message delivery">
          <DataTable
            data-testid="staff-messages"
            caption="Message delivery"
            rows={paged.rows}
            rowKey={(message) => message.id}
            columns={[
              {
                key: "status",
                header: "Status",
                cell: (message) => <StatusBadge value={message.status} />,
              },
              {
                key: "campaign",
                header: "Campaign",
                cell: (message) => (
                  <span dir="auto">
                    {campaignLabel(message.campaign_id, campaigns)}
                  </span>
                ),
              },
              {
                key: "lead",
                header: "Lead / username",
                cell: (message) => (
                  <span dir="auto">
                    {leads[message.lead_id] || message.lead_id}
                  </span>
                ),
              },
              {
                key: "keyword",
                header: "Trigger keyword",
                cell: (message) =>
                  message.trigger_keyword ? (
                    <code dir="auto">{message.trigger_keyword}</code>
                  ) : (
                    <span className="muted">Not available</span>
                  ),
              },
              {
                key: "type",
                header: "Message type",
                cell: (message) => (
                  <StatusBadge
                    value={message.message_type || "final_delivery"}
                    tone={
                      message.message_type === "follow_prompt"
                        ? "info"
                        : message.message_type === "retry"
                          ? "warning"
                          : "neutral"
                    }
                  >
                    {messageTypeLabel(message.message_type)}
                  </StatusBadge>
                ),
              },
              {
                key: "sent",
                header: "Sent at",
                cell: (message) =>
                  message.status === "sent" && message.created_at
                    ? new Date(message.created_at).toLocaleString()
                    : "Not sent",
              },
              {
                key: "error",
                header: "Error / retry",
                cell: (message) => (
                  <div className="staff-many-stack">
                    <div>
                      <StatusBadge value="retries" tone="neutral">
                        {retriesLabel(message.retry_count)}
                      </StatusBadge>{" "}
                      {message.error_message ? (
                        <span className="staff-many-error" dir="auto">
                          {message.error_message}
                        </span>
                      ) : (
                        <span className="muted">No error</span>
                      )}
                    </div>
                    {canRetry(message) && (
                      <Button
                        variant="quiet"
                        data-testid={`retry-${message.id}`}
                        disabled={retrying[message.id]}
                        onClick={() => void retry(message.id)}
                      >
                        Retry
                      </Button>
                    )}
                    <details>
                      <summary>Technical details</summary>
                      <div className="staff-many-tech" dir="ltr">
                        <span>Comment: {message.comment_id || "None"}</span>
                        <span>
                          Campaign:{" "}
                          {hasCampaign(message.campaign_id)
                            ? message.campaign_id
                            : "Cold DM (no campaign)"}
                        </span>
                        <span>Lead: {message.lead_id}</span>
                      </div>
                    </details>
                  </div>
                ),
              },
            ]}
          />
          <Pager paged={paged} onPage={setPage} noun="Messages" />
        </Card>
      </PageState>
      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  );
}
