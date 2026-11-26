"use client";

import Link from "next/link";
import { useState } from "react";

import { ManyError, manyRequest } from "@/lib/many";
import { PageState, type PageStatus } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  Card,
  DataTable,
  Empty,
  Loading,
  Notice,
  PageHeader,
  StatusBadge,
  Toast,
} from "@/lib/ui";
import {
  conversationControl,
  filterConversations,
  PLATFORM_FILTERS,
  STATUS_FILTERS,
} from "@/lib/many-staff/conversations";
import { Pager } from "@/lib/many-staff/pager";
import { paginate } from "@/lib/many-staff/paging";
import type {
  ManyConversation,
  ManyConversationDetail,
} from "@/lib/many-staff/types";

import "@/app/staff-many-screen.css";

const STAFF = { kind: "staff" } as const;

function SharedInboxMark({ row }: { row: ManyConversation }) {
  const control = conversationControl(row);
  if (control.kind !== "shared_inbox") return null;
  return control.href ? (
    <Link href={control.href} data-testid="open-shared-inbox">
      Open in the shared inbox
    </Link>
  ) : (
    <StatusBadge
      value="shared_inbox"
      tone="info"
      data-testid="handled-in-shared-inbox"
    >
      Handled in the shared inbox
    </StatusBadge>
  );
}

/**
 * Many's AI-continued DM conversations (platform staff only). Rows delegated to the shared
 * inbox are read-only here: no Take over, no Resume bot.
 */
export default function StaffConversationsPage() {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<ManyConversationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const { data, status, reload } = useManyData<ManyConversation[]>(
    () => manyRequest<ManyConversation[]>(STAFF, "GET", "conversations"),
    "conversations",
  );

  async function openThread(id: string) {
    setDetailLoading(true);
    setActionError(null);
    try {
      setSelected(
        await manyRequest<ManyConversationDetail>(
          STAFF,
          "GET",
          `conversations/${encodeURIComponent(id)}`,
        ),
      );
    } catch (caught) {
      setActionError(
        caught instanceof ManyError
          ? caught.message
          : "The conversation could not be loaded.",
      );
    } finally {
      setDetailLoading(false);
    }
  }

  async function act(id: string, action: "take-over" | "resume-bot") {
    setPending(true);
    setActionError(null);
    try {
      await manyRequest(
        STAFF,
        "POST",
        `conversations/${encodeURIComponent(id)}/${action}`,
      );
      setToast(
        action === "take-over"
          ? "Bot paused. You have taken over this conversation."
          : "Bot resumed for this conversation.",
      );
      reload();
      await openThread(id);
    } catch (caught) {
      setActionError(
        caught instanceof ManyError
          ? caught.message
          : "The action could not be completed.",
      );
    } finally {
      setPending(false);
    }
  }

  const filtered = filterConversations(
    data ?? [],
    statusFilter,
    platformFilter,
  );
  const paged = paginate(filtered, page);
  let shown: PageStatus = status;
  if (status.kind === "ready" && filtered.length === 0) {
    shown = {
      kind: "empty",
      message:
        "No conversations yet. They appear once a lead replies after an AI-enabled campaign message.",
    };
  }
  const control = selected ? conversationControl(selected) : null;

  return (
    <div className="staff-many-page">
      <PageHeader
        title="Instagram conversations"
        purpose="Monitor AI-assisted DM conversations and take over when needed. Platform staff only."
      />
      {actionError && (
        <Notice message={actionError} tone="error" scope="item" />
      )}
      <div className="staff-many-split">
        <Card title="Active threads">
          <div className="staff-many-chips" role="group" aria-label="Platform">
            {PLATFORM_FILTERS.map((platform) => (
              <Button
                key={platform}
                variant="quiet"
                aria-pressed={platformFilter === platform}
                onClick={() => {
                  setPlatformFilter(platform);
                  setPage(1);
                }}
              >
                {platform === "all" ? "All platforms" : platform}
              </Button>
            ))}
          </div>
          <div className="staff-many-chips" role="group" aria-label="Status">
            {STATUS_FILTERS.map((value) => (
              <Button
                key={value}
                variant="quiet"
                aria-pressed={statusFilter === value}
                onClick={() => {
                  setStatusFilter(value);
                  setPage(1);
                }}
              >
                {value === "all" ? "All" : value.replaceAll("_", " ")}
              </Button>
            ))}
          </div>
          <PageState status={shown} homeHref="/platform">
            <DataTable
              data-testid="staff-conversations"
              caption="Conversations"
              rows={paged.rows}
              rowKey={(row) => row.id}
              columns={[
                {
                  key: "status",
                  header: "Status",
                  cell: (row) => <StatusBadge value={row.status} />,
                },
                {
                  key: "lead",
                  header: "Lead",
                  cell: (row) => (
                    <span dir="auto">{row.lead_username || row.lead_id}</span>
                  ),
                },
                {
                  key: "platform",
                  header: "Platform",
                  cell: (row) => (
                    <StatusBadge
                      value={row.platform || "unknown"}
                      tone="info"
                    />
                  ),
                },
                {
                  key: "source",
                  header: "Source",
                  cell: (row) =>
                    row.lead_source === "cold_dm" ? "Cold DM" : "Campaign",
                },
                {
                  key: "campaign",
                  header: "Campaign",
                  cell: (row) => (
                    <span dir="auto">
                      {row.campaign_name || row.campaign_id || "Direct DM"}
                    </span>
                  ),
                },
                {
                  key: "turns",
                  header: "Turns",
                  cell: (row) => row.turn_count,
                },
                {
                  key: "last",
                  header: "Last activity",
                  cell: (row) =>
                    row.last_message_at
                      ? new Date(row.last_message_at).toLocaleString()
                      : "None",
                },
                {
                  key: "actions",
                  header: "Thread",
                  cell: (row) => (
                    <div className="staff-many-stack">
                      <Button
                        variant="quiet"
                        data-testid={`open-thread-${row.id}`}
                        aria-pressed={selected?.id === row.id}
                        onClick={() => void openThread(row.id)}
                      >
                        View thread
                      </Button>
                      <SharedInboxMark row={row} />
                    </div>
                  ),
                },
              ]}
            />
            <Pager paged={paged} onPage={setPage} noun="Conversations" />
          </PageState>
        </Card>

        <Card title="Thread" data-testid="staff-thread">
          {detailLoading && <Loading />}
          {!detailLoading && !selected && (
            <Empty>Choose a conversation to see its thread.</Empty>
          )}
          {!detailLoading && selected && control && (
            <div className="staff-many-thread">
              <div className="staff-many-thread-head">
                <div>
                  <strong dir="auto">
                    {selected.lead_username || selected.lead_id}
                  </strong>
                  <div className="muted" dir="auto">
                    {selected.campaign_name}
                  </div>
                </div>
                <StatusBadge value={selected.status} />
              </div>
              <ol className="staff-many-messages">
                {selected.messages.length === 0 ? (
                  <li className="muted">No messages yet.</li>
                ) : (
                  selected.messages.map((message) => (
                    <li
                      key={message.id}
                      data-direction={message.direction ?? "outbound"}
                    >
                      <p dir="auto">{message.content}</p>
                      <span className="muted">
                        {message.created_at
                          ? new Date(message.created_at).toLocaleTimeString()
                          : ""}
                        {message.status === "failed" && (
                          <strong className="staff-many-error">
                            {" "}
                            Failed to send
                          </strong>
                        )}
                      </span>
                    </li>
                  ))
                )}
              </ol>
              <div className="staff-many-thread-actions">
                {control.kind === "shared_inbox" ? (
                  <SharedInboxMark row={selected} />
                ) : control.kind === "take_over" ? (
                  <Button
                    variant="quiet"
                    data-testid="take-over"
                    disabled={pending}
                    onClick={() => void act(selected.id, "take-over")}
                  >
                    Take over
                  </Button>
                ) : (
                  <Button
                    variant="quiet"
                    data-testid="resume-bot"
                    disabled={pending}
                    onClick={() => void act(selected.id, "resume-bot")}
                  >
                    Resume bot
                  </Button>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>
      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  );
}
