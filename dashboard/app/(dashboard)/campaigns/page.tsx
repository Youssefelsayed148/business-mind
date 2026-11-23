"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { BarChart3, Pencil, Plus, Trash2, X } from "lucide-react";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { Highlight } from "@/components/ui/Highlight";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { api } from "@/lib/api";
import { useCan } from "@/lib/permissions";
import { useToast } from "@/components/ToastProvider";
import type { Campaign, InstagramAccount } from "@/lib/types";

type CampaignFilter = "all" | "active" | "paused" | "archived";
type CampaignUiStatus = "active" | "paused" | "archived";

const filters: { label: string; value: CampaignFilter }[] = [
  { label: "All", value: "all" },
  { label: "Active", value: "active" },
  { label: "Paused", value: "paused" },
  { label: "Archived", value: "archived" },
];

function campaignStatus(campaign: Campaign): CampaignUiStatus {
  return campaign.status === "archived" || campaign.status === "active" ? campaign.status : "paused";
}

function formatDateTime(value?: string | null): string {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function MetricPill({ label, value, tone = "slate" }: { label: string; value: number; tone?: "slate" | "emerald" | "red" }) {
  const tones = {
    slate: "border-slate-200 bg-slate-50 text-slate-700",
    emerald: "border-emerald-200 bg-mint text-emerald-700",
    red: "border-red-200 bg-red-50 text-red-700",
  };

  return (
    <div className={`min-w-0 rounded-md border px-2 py-1.5 ${tones[tone]}`}>
      <div className="truncate text-[11px] font-bold uppercase text-slate-500">{label}</div>
      <div className="mt-0.5 text-base font-bold leading-none text-ink">{value}</div>
    </div>
  );
}

function KeywordChips({ campaign }: { campaign: Campaign }) {
  if (campaign.keywords.length === 0) {
    return <span className="text-sm text-muted">No keywords</span>;
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {campaign.keywords.slice(0, 4).map((keyword) => (
        <span key={keyword.id} dir="auto" className="inline-flex max-w-full rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700">
          <Highlight text={keyword.normalized_keyword} />
        </span>
      ))}
      {campaign.keywords.length > 4 ? <span className="text-xs font-semibold text-muted">+{campaign.keywords.length - 4}</span> : null}
    </div>
  );
}

function DeliveryModeBadge({ value }: { value?: Campaign["delivery_mode"] }) {
  const isFollowPrompt = value === "follow_prompt";
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold shadow-sm ${isFollowPrompt ? "border-violet-200 bg-violet-50 text-violet-700" : "border-slate-200 bg-slate-50 text-slate-700"}`}>
      {isFollowPrompt ? "Follow Prompt" : "Instant"}
    </span>
  );
}

function campaignTargetLabel(campaign: Campaign): string {
  if (campaign.target_scope !== "specific_media") {
    return "Any media";
  }
  const type = campaign.target_media_type && campaign.target_media_type !== "unknown"
    ? campaign.target_media_type.charAt(0).toUpperCase() + campaign.target_media_type.slice(1)
    : "Instagram post";
  const fallback = campaign.target_media_type === "reel" ? "Instagram reel" : "Instagram post";
  return [type, campaign.target_media_label || fallback].join(" \u00b7 ");
  return `${type} · ${campaign.target_media_label || fallback}`;
}

function AccountBadge({ connected }: { connected: boolean }) {
  return <Badge value={connected ? "connected" : "disconnected"} />;
}

function DeleteCampaignModal({
  campaigns,
  error,
  deleting,
  onCancel,
  onConfirm,
}: {
  campaigns: Campaign[];
  error: string | null;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [confirmation, setConfirmation] = useState("");
  const requiredText = campaigns.length === 1 ? `delete ${campaigns[0].name}` : "delete campaigns";
  const canDelete = confirmation.trim().toLowerCase() === requiredText.toLowerCase() && campaigns.length > 0 && !deleting;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-xl border border-red-100 bg-white shadow-xl shadow-slate-950/15">
        <div className="flex items-start justify-between gap-4 border-b border-line p-5">
          <div>
            <h2 className="text-lg font-bold text-ink">Permanently delete campaign?</h2>
            <p className="mt-1 text-sm leading-6 text-muted">This cannot be undone. Deleted campaigns are removed from the campaign list permanently.</p>
          </div>
          <button type="button" onClick={onCancel} className="rounded-lg border border-line bg-white p-2 text-slate-500 hover:bg-slate-50 hover:text-ink" aria-label="Close delete confirmation">
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <div className="grid gap-4 p-5">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="text-xs font-bold uppercase text-slate-500">Selected campaigns</div>
            <ul className="mt-2 grid gap-1 text-sm font-semibold text-slate-800">
              {campaigns.map((campaign) => <li key={campaign.id} className="truncate">{campaign.name}</li>)}
            </ul>
          </div>
          <label className="grid gap-2 text-sm font-semibold text-ink">
            Type <code className="rounded bg-red-50 px-1.5 py-0.5 font-mono text-red-700">{requiredText}</code>
            <input
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              className="h-11 rounded-lg border border-line bg-white px-3 text-sm font-medium text-ink outline-none transition focus:border-red-300 focus:ring-4 focus:ring-red-100"
              autoFocus
            />
          </label>
          {error ? <div className="rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">{error}</div> : null}
        </div>
        <div className="flex flex-col-reverse gap-2 border-t border-line p-5 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onCancel} disabled={deleting}>Cancel</Button>
          <Button type="button" variant="danger" onClick={onConfirm} disabled={!canDelete} className="gap-2">
            <Trash2 className="h-4 w-4" aria-hidden="true" />
            Delete permanently
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [accounts, setAccounts] = useState<Record<string, InstagramAccount>>({});
  const [filter, setFilter] = useState<CampaignFilter>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const canManageCampaigns = useCan("manage_campaigns");
  const canDeleteCampaigns = useCan("delete_campaigns");
  const toast = useToast();

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [campaignData, accountData] = await Promise.all([
        api.get<Campaign[]>("/campaigns"),
        api.get<InstagramAccount[]>("/instagram/accounts"),
      ]);
      setCampaigns(campaignData);
      setAccounts(Object.fromEntries(accountData.map((account) => [account.id, account])));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load campaigns");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const visibleCampaigns = useMemo(() => {
    if (filter === "all") return campaigns;
    return campaigns.filter((campaign) => campaignStatus(campaign) === filter);
  }, [campaigns, filter]);

  const tabCounts = useMemo(() => ({
    all: campaigns.length,
    active: campaigns.filter((c) => campaignStatus(c) === "active").length,
    paused: campaigns.filter((c) => campaignStatus(c) === "paused").length,
    archived: campaigns.filter((c) => campaignStatus(c) === "archived").length,
  }), [campaigns]);

  const selectedArchivedIds = Array.from(selected).filter((id) => {
    const campaign = campaigns.find((item) => item.id === id);
    return campaign && campaignStatus(campaign) === "archived";
  });

  function updateCampaign(next: Campaign) {
    setCampaigns((items) => items.map((item) => (item.id === next.id ? next : item)));
  }

  async function runAction(campaign: Campaign, action: "activate" | "pause" | "archive" | "unarchive") {
    setActionError(null);
    setPending((next) => ({ ...next, [campaign.id]: action }));
    try {
      const updated = await api.post<Campaign>(`/campaigns/${campaign.id}/${action}`);
      updateCampaign(updated);
      toast.success(`Campaign ${action === "unarchive" ? "unarchived" : `${action}d`}.`);
    } catch (err) {
      const message = err instanceof Error ? err.message : `Failed to ${action} campaign`;
      setActionError(message);
      toast.error(message);
    } finally {
      setPending((next) => {
        const copy = { ...next };
        delete copy[campaign.id];
        return copy;
      });
    }
  }

  const selectedArchivedCampaigns = useMemo(
    () => campaigns.filter((campaign) => selected.has(campaign.id) && campaignStatus(campaign) === "archived"),
    [campaigns, selected],
  );

  function openDeleteModal() {
    setDeleteError(null);
    setActionError(null);
    if (selectedArchivedIds.length !== selected.size) {
      setActionError("Only archived campaigns can be permanently deleted.");
      toast.warning("Only archived campaigns can be permanently deleted.");
      return;
    }
    if (selectedArchivedCampaigns.length === 0) return;
    setDeleteModalOpen(true);
  }

  async function deleteSelectedCampaigns() {
    const ids = selectedArchivedCampaigns.map((campaign) => campaign.id);
    if (ids.length === 0) return;
    setDeleteError(null);
    setPending((next) => ({ ...next, ...Object.fromEntries(ids.map((id) => [id, "delete"])) }));
    try {
      await Promise.all(ids.map((id) => api.delete(`/campaigns/${id}`)));
      setCampaigns((items) => items.filter((item) => !ids.includes(item.id)));
      setSelected((current) => new Set(Array.from(current).filter((id) => !ids.includes(id))));
      setDeleteModalOpen(false);
      toast.success("Campaign deleted permanently.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to delete campaign";
      setDeleteError(message);
      toast.error(message);
      await load();
    } finally {
      setPending((next) => {
        const copy = { ...next };
        ids.forEach((id) => delete copy[id]);
        return copy;
      });
    }
  }

  return (
    <div className="grid w-full min-w-0 max-w-full gap-6 overflow-x-hidden">
      <PageHeader title="Campaigns" description="Create and manage comment-triggered message campaigns across connected accounts.">
        {canManageCampaigns ? <Link href="/campaigns/new" className="min-w-0"><Button type="button" className="gap-2"><Plus className="h-4 w-4" aria-hidden="true" />New campaign</Button></Link> : null}
      </PageHeader>
      <Panel className="w-full max-w-full overflow-hidden p-4">
        <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-ink">Campaign list</h2>
            <p className="mt-1 text-sm text-muted">Track campaign lifecycle separately from account connectivity, trigger volume, and delivery results.</p>
          </div>
          <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
            <div className="inline-flex min-w-0 flex-wrap rounded-lg border border-line bg-slate-50 p-1">
              {filters.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setFilter(item.value)}
                  className={`inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-semibold transition ${filter === item.value ? "bg-white text-ink shadow-sm" : "text-muted hover:text-ink"}`}
                >
                  {item.label}
                  {tabCounts[item.value] > 0 ? (
                    <span className={`rounded-full px-1.5 py-0.5 text-[11px] font-bold leading-none tabular-nums ${filter === item.value ? "bg-slate-100 text-slate-600" : "bg-slate-200 text-slate-500"}`}>
                      {tabCounts[item.value]}
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
            {canDeleteCampaigns ? <Button
              type="button"
              variant="danger"
              className="gap-2"
              disabled={selectedArchivedIds.length === 0}
              onClick={openDeleteModal}
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
              Delete selected
            </Button> : null}
          </div>
        </div>
        <DataState loading={loading} error={error || actionError} />
        {loading ? <TableSkeleton rows={5} columns={6} /> : null}
        {!loading && !error && campaigns.length === 0 ? <EmptyState title="No campaigns yet" message="Create a campaign to start matching comments and sending replies." /> : null}
        {!loading && !error && campaigns.length > 0 && visibleCampaigns.length === 0 ? <EmptyState title="No campaigns in this view" message="Change the filter to see other campaign statuses." /> : null}
        {visibleCampaigns.length > 0 ? (
          <div className="grid w-full min-w-0 max-w-full gap-2 overflow-hidden">
            <div className="campaign-list-grid hidden rounded-lg border border-line bg-slate-50 px-3 py-2 text-[11px] font-bold uppercase text-slate-500 xl:grid xl:gap-1">
              <div />
              <div className="min-w-0">Campaign</div>
              <div className="min-w-0">Account</div>
              <div className="min-w-0">Keywords</div>
              <div className="min-w-0">Status</div>
              <div className="min-w-0">Metrics</div>
              <div className="min-w-0">Actions</div>
            </div>
            {visibleCampaigns.map((campaign) => {
              const account = accounts[campaign.instagram_account_id];
              const accountName = account?.username || account?.ig_user_id || "No account";
              const accountConnected = (account?.status || "disconnected").toLowerCase() === "connected";
              const status = campaignStatus(campaign);
              const isPending = Boolean(pending[campaign.id]);

              return (
                <article key={campaign.id} className="w-full min-w-0 max-w-full overflow-hidden rounded-xl border border-line/80 bg-white p-3 shadow-sm shadow-slate-200/60 transition hover:border-emerald-200 hover:shadow-md">
                  <div className="campaign-list-grid grid min-w-0 max-w-full gap-3 xl:items-center xl:gap-1">
                    <input
                      type="checkbox"
                      aria-label={`Select ${campaign.name}`}
                      checked={selected.has(campaign.id)}
                      onChange={(event) => {
                        setSelected((current) => {
                          const next = new Set(current);
                          event.target.checked ? next.add(campaign.id) : next.delete(campaign.id);
                          return next;
                        });
                      }}
                      disabled={!canDeleteCampaigns || status !== "archived"}
                      className="min-w-0 h-4 w-4 rounded border-slate-300 text-accent focus:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-40"
                    />
                    <div className="flex min-w-0 gap-3">
                      <Avatar label={campaign.name} size="lg" />
                      <div className="min-w-0">
                        <div className="flex min-w-0 flex-wrap items-center gap-2">
                          <h3 className="truncate text-base font-bold text-ink">{campaign.name}</h3>
                          <DeliveryModeBadge value={campaign.delivery_mode} />
                        </div>
                        <p className="mt-1 truncate text-xs font-semibold text-muted">{campaignTargetLabel(campaign)}</p>
                        <p className="mt-0.5 truncate text-xs font-medium text-muted">Created {formatDateTime(campaign.created_at)}</p>
                        {campaign.target_scope === "specific_media" && campaign.target_media_url ? (
                          <a
                            href={campaign.target_media_url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-0.5 block truncate text-xs font-medium text-accent hover:underline"
                          >
                            {campaign.target_media_url}
                          </a>
                        ) : null}
                      </div>
                    </div>
                    <div className="min-w-0">
                      <div className="text-[11px] font-bold uppercase text-slate-500 lg:hidden">Account</div>
                      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-semibold text-ink">{accountName}</span>
                        <AccountBadge connected={accountConnected} />
                      </div>
                    </div>
                    <div className="min-w-0">
                      <div className="mb-1.5 text-[11px] font-bold uppercase text-slate-500 lg:hidden">Keywords</div>
                      <KeywordChips campaign={campaign} />
                    </div>
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <Badge value={status} />
                    </div>
                    <div className="grid min-w-0 grid-cols-3 gap-1">
                      <MetricPill label="Triggers" value={campaign.total_triggers} />
                      <MetricPill label="Sent" value={campaign.successful_sends} tone="emerald" />
                      <MetricPill label="Failed" value={campaign.failed_sends} tone="red" />
                    </div>
                    <div className="grid min-w-0 grid-cols-2 gap-2">
                      {canManageCampaigns ? <Link href={`/campaigns/${campaign.id}`} className="min-w-0">
                        <Button type="button" variant="edit" className="h-9 w-full min-w-0 gap-1.5 px-2 text-xs"><Pencil className="h-3.5 w-3.5" aria-hidden="true" />Edit</Button>
                      </Link> : <span />}
                      <Link href={`/campaigns/${campaign.id}/stats`} className="min-w-0">
                        <Button type="button" variant="stats" className="h-9 w-full min-w-0 gap-1.5 px-2 text-xs"><BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />Stats</Button>
                      </Link>
                      {canManageCampaigns && status === "active" ? (
                        <>
                          <Button type="button" variant="pause" className="h-9 w-full min-w-0 px-1.5 text-xs" disabled={isPending} onClick={() => runAction(campaign, "pause")}>Pause</Button>
                          <Button type="button" variant="archive" className="h-9 w-full min-w-0 px-1.5 text-xs" disabled={isPending} onClick={() => runAction(campaign, "archive")}>Archive</Button>
                        </>
                      ) : null}
                      {canManageCampaigns && status === "paused" ? (
                        <>
                          <Button type="button" variant="activate" className="h-9 w-full min-w-0 px-1.5 text-xs" disabled={isPending || !accountConnected} title={!accountConnected ? "Reconnect account before activating" : undefined} onClick={() => runAction(campaign, "activate")}>Activate</Button>
                          <Button type="button" variant="archive" className="h-9 w-full min-w-0 px-1.5 text-xs" disabled={isPending} onClick={() => runAction(campaign, "archive")}>Archive</Button>
                        </>
                      ) : null}
                      {canManageCampaigns && status === "archived" ? (
                        <>
                          <Button type="button" variant="secondary" className="col-span-2 h-9 w-full min-w-0 px-1.5 text-xs" disabled={isPending} onClick={() => runAction(campaign, "unarchive")}>Unarchive</Button>
                        </>
                      ) : null}
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        ) : null}
      </Panel>
      {deleteModalOpen ? (
        <DeleteCampaignModal
          campaigns={selectedArchivedCampaigns}
          error={deleteError}
          deleting={selectedArchivedCampaigns.some((campaign) => pending[campaign.id] === "delete")}
          onCancel={() => setDeleteModalOpen(false)}
          onConfirm={deleteSelectedCampaigns}
        />
      ) : null}
    </div>
  );
}
