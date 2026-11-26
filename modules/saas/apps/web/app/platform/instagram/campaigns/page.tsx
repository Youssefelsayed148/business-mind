"use client";

import { useMemo, useState } from "react";

import { ManyError } from "@/lib/many";
import { staffGet, staffSend } from "@/lib/many-instagram/calls";
import {
  campaignFilterCounts,
  campaignUiStatus,
  deleteConfirmText,
  deleteConfirmed,
  filterCampaigns,
  formatDateTime,
  isConnected,
  targetLabel,
  type CampaignFilter,
} from "@/lib/many-instagram/helpers";
import type { Campaign, InstagramAccount } from "@/lib/many-instagram/types";
import { PageState } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  Card,
  DataTable,
  Dialog,
  Empty,
  LinkButton,
  Notice,
  PageHeader,
  StatusBadge,
  TabPanel,
  Tabs,
  type Column,
} from "@/lib/ui";

import "@/app/instagram-screen.css";

const BASE = "/platform/instagram/campaigns";
type Action = "activate" | "pause" | "archive" | "unarchive";
const DONE: Record<Action, string> = {
  activate: "Campaign activated.",
  pause: "Campaign paused.",
  archive: "Campaign archived.",
  unarchive: "Campaign unarchived.",
};
const FILTERS: { id: CampaignFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "active", label: "Active" },
  { id: "paused", label: "Paused" },
  { id: "archived", label: "Archived" },
];

interface ListData {
  campaigns: Campaign[];
  accounts: Record<string, InstagramAccount>;
}

function plain(caught: unknown, fallback: string) {
  return caught instanceof ManyError ? caught.message : fallback;
}

/** Instagram campaigns across all accounts, for platform staff. */
export default function InstagramCampaignsPage() {
  const { data, status, reload } = useManyData<ListData>(
    async () => {
      const [campaigns, accounts] = await Promise.all([
        staffGet<Campaign[]>("/campaigns"),
        staffGet<InstagramAccount[]>("/instagram/accounts"),
      ]);
      return {
        campaigns,
        accounts: Object.fromEntries(accounts.map((a) => [a.id, a])),
      };
    },
    "campaigns",
    {
      isEmpty: (d) => d.campaigns.length === 0,
      emptyMessage:
        "No campaigns yet. Create one to start matching comments and sending replies.",
    },
  );
  const [filter, setFilter] = useState<CampaignFilter>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const campaigns = useMemo(() => data?.campaigns ?? [], [data]);
  const accounts = data?.accounts ?? {};
  const visible = filterCampaigns(campaigns, filter);
  const counts = campaignFilterCounts(campaigns);
  const selectedCampaigns = campaigns.filter(
    (c) => selected.has(c.id) && campaignUiStatus(c.status) === "archived",
  );
  const names = selectedCampaigns.map((c) => c.name);

  async function run(campaign: Campaign, action: Action) {
    setActionError(null);
    setNotice(null);
    setPending((p) => new Set(p).add(campaign.id));
    try {
      await staffSend<Campaign>("POST", `/campaigns/${campaign.id}/${action}`);
      setNotice(DONE[action]);
      reload();
    } catch (caught) {
      setActionError(plain(caught, `Could not ${action} the campaign.`));
    } finally {
      setPending((p) => {
        const next = new Set(p);
        next.delete(campaign.id);
        return next;
      });
    }
  }

  async function deleteSelected() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await Promise.all(
        selectedCampaigns.map((c) => staffSend("DELETE", `/campaigns/${c.id}`)),
      );
      setSelected(new Set());
      setDeleteOpen(false);
      setTyped("");
      setNotice("Campaign deleted permanently.");
      reload();
    } catch (caught) {
      setDeleteError(plain(caught, "Could not delete the campaign."));
      reload();
    } finally {
      setDeleting(false);
    }
  }

  const columns: Column<Campaign>[] = [
    {
      key: "select",
      header: <span className="sr-only">Select</span>,
      cell: (c) => (
        <input
          type="checkbox"
          aria-label={`Select ${c.name}`}
          data-testid={`ig-select-${c.id}`}
          checked={selected.has(c.id)}
          disabled={campaignUiStatus(c.status) !== "archived"}
          onChange={(event) =>
            setSelected((current) => {
              const next = new Set(current);
              if (event.target.checked) next.add(c.id);
              else next.delete(c.id);
              return next;
            })
          }
        />
      ),
    },
    {
      key: "campaign",
      header: "Campaign",
      className: "ig-col-wide",
      cell: (c) => (
        <div className="ig-cell">
          <strong dir="auto">{c.name}</strong>
          <span className="muted">
            {c.delivery_mode === "follow_prompt" ? "Follow prompt" : "Instant"}{" "}
            &middot; {targetLabel(c)}
          </span>
          <span className="muted">Created {formatDateTime(c.created_at)}</span>
          {c.target_scope === "specific_media" && c.target_media_url && (
            <a
              href={c.target_media_url}
              target="_blank"
              rel="noreferrer noopener"
              dir="ltr"
              className="ig-url"
            >
              {c.target_media_url}
            </a>
          )}
        </div>
      ),
    },
    {
      key: "account",
      header: "Account",
      cell: (c) => {
        const account = accounts[c.instagram_account_id];
        return (
          <div className="ig-cell">
            <span dir="auto">
              {account ? account.username || account.ig_user_id : "No account"}
            </span>
            <StatusBadge
              value={
                account && isConnected(account) ? "connected" : "disconnected"
              }
              tone={account && isConnected(account) ? "success" : "neutral"}
            />
          </div>
        );
      },
    },
    {
      key: "keywords",
      header: "Keywords",
      cell: (c) =>
        c.keywords.length === 0 ? (
          <span className="muted">No keywords</span>
        ) : (
          <span className="ig-chips">
            {c.keywords.slice(0, 4).map((k) => (
              <span key={k.id} className="ig-chip" dir="auto">
                {k.normalized_keyword}
              </span>
            ))}
            {c.keywords.length > 4 && (
              <span className="muted">+{c.keywords.length - 4}</span>
            )}
          </span>
        ),
    },
    {
      key: "status",
      header: "Status",
      cell: (c) => <StatusBadge value={campaignUiStatus(c.status)} />,
    },
    {
      key: "metrics",
      header: "Triggers / sent / failed",
      cell: (c) => (
        <span dir="ltr">
          {c.total_triggers} / {c.successful_sends} / {c.failed_sends}
        </span>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      cell: (c) => {
        const ui = campaignUiStatus(c.status);
        const busy = pending.has(c.id);
        const accountOk = Boolean(
          accounts[c.instagram_account_id] &&
          isConnected(accounts[c.instagram_account_id]),
        );
        return (
          <div className="ig-actions">
            <LinkButton
              size="sm"
              href={`${BASE}/${c.id}`}
              data-testid={`ig-edit-${c.id}`}
            >
              Edit
            </LinkButton>
            <LinkButton
              size="sm"
              href={`${BASE}/${c.id}/stats`}
              data-testid={`ig-stats-${c.id}`}
            >
              Stats
            </LinkButton>
            {ui === "active" && (
              <>
                <Button
                  variant="quiet"
                  disabled={busy}
                  data-testid={`ig-pause-${c.id}`}
                  onClick={() => void run(c, "pause")}
                >
                  Pause
                </Button>
                <Button
                  variant="quiet"
                  disabled={busy}
                  data-testid={`ig-archive-${c.id}`}
                  onClick={() => void run(c, "archive")}
                >
                  Archive
                </Button>
              </>
            )}
            {ui === "paused" && (
              <>
                <Button
                  disabled={busy || !accountOk}
                  title={
                    !accountOk
                      ? "Reconnect the account before activating"
                      : undefined
                  }
                  data-testid={`ig-activate-${c.id}`}
                  onClick={() => void run(c, "activate")}
                >
                  Activate
                </Button>
                <Button
                  variant="quiet"
                  disabled={busy}
                  data-testid={`ig-archive-${c.id}`}
                  onClick={() => void run(c, "archive")}
                >
                  Archive
                </Button>
              </>
            )}
            {ui === "archived" && (
              <Button
                variant="quiet"
                disabled={busy}
                data-testid={`ig-unarchive-${c.id}`}
                onClick={() => void run(c, "unarchive")}
              >
                Unarchive
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <div className="ig-page" data-testid="ig-campaigns">
      <PageHeader
        title="Instagram campaigns"
        purpose="Comment-triggered message campaigns across all connected accounts. Platform staff only."
        actions={
          <LinkButton
            href={`${BASE}/new`}
            variant="primary"
            icon="plus"
            data-testid="ig-new-campaign"
          >
            New campaign
          </LinkButton>
        }
      />
      <PageState status={status} homeHref="/platform">
        <Card
          title="Campaign list"
          actions={
            <Button
              variant="danger"
              disabled={selectedCampaigns.length === 0}
              data-testid="ig-delete-selected"
              onClick={() => {
                setDeleteError(null);
                setTyped("");
                setDeleteOpen(true);
              }}
            >
              Delete selected
            </Button>
          }
        >
          <Tabs
            idPrefix="ig-campaign-filter"
            value={filter}
            onChange={(id) => setFilter(id as CampaignFilter)}
            aria-label="Campaign status"
            tabs={FILTERS.map((f) => ({
              id: f.id,
              label: `${f.label} (${counts[f.id]})`,
              testId: `ig-filter-${f.id}`,
            }))}
          />
          <TabPanel idPrefix="ig-campaign-filter" tabId={filter} active>
            {actionError && (
              <Notice tone="error" message={actionError} scope="item" />
            )}
            {notice && <Notice message={notice} scope="item" />}
            <DataTable
              caption="Instagram campaigns"
              columns={columns}
              rows={visible}
              rowKey={(c) => c.id}
              empty={
                <Empty>
                  No campaigns in this view. Change the filter to see the
                  others.
                </Empty>
              }
            />
          </TabPanel>
        </Card>
      </PageState>

      <Dialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        title="Permanently delete campaigns?"
        data-testid="ig-delete-dialog"
      >
        <p>
          This cannot be undone. Deleted campaigns are removed from the list
          permanently.
        </p>
        <ul>
          {names.map((name, index) => (
            <li key={index} dir="auto">
              {name}
            </li>
          ))}
        </ul>
        <div className="field">
          <label htmlFor="ig-delete-confirm">
            Type <code dir="auto">{deleteConfirmText(names)}</code> to confirm
          </label>
          <input
            id="ig-delete-confirm"
            data-testid="ig-delete-confirm"
            dir="auto"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
        </div>
        {deleteError && (
          <Notice tone="error" message={deleteError} scope="item" />
        )}
        <div className="action-row">
          <Button
            variant="quiet"
            disabled={deleting}
            onClick={() => setDeleteOpen(false)}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={!deleteConfirmed(typed, names) || deleting}
            data-testid="ig-delete-confirm-button"
            onClick={() => void deleteSelected()}
          >
            {deleting ? "Deleting..." : "Delete permanently"}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
