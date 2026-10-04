"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AlertTriangle, RefreshCw, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  api,
  getCurrentWorkspaceMembership,
  type WorkspaceMembership,
} from "@/lib/api";
import type { WhatsappAccount } from "@/lib/types";
import type { OutreachHealth, WhatsappCampaign } from "@/lib/whatsapp";
import {
  WorkspaceRoleProvider,
  workspaceCan,
} from "@/lib/workspacePermissions";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { useToast } from "@/components/ToastProvider";

type WhatsappContextValue = {
  account: WhatsappAccount | null;
  accounts: WhatsappAccount[];
  setAccountId: (id: string) => void;
  health: OutreachHealth | null;
  refreshHealth: () => Promise<void>;
  membership: WorkspaceMembership | null;
  outreachDisabled: boolean;
};
const WhatsappContext = createContext<WhatsappContextValue | null>(null);
export function useWhatsapp() {
  const value = useContext(WhatsappContext);
  if (!value) throw new Error("useWhatsapp must be used inside WhatsappShell");
  return value;
}

function ResumeDialog({
  accountId,
  onClose,
  onDone,
}: {
  accountId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [campaigns, setCampaigns] = useState<WhatsappCampaign[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => {
    api
      .get<WhatsappCampaign[]>(
        `/whatsapp/campaigns?account_id=${accountId}&campaign_status=paused`,
      )
      .then((rows) => {
        setCampaigns(rows);
        setCampaignId(rows[0]?.id || "");
      })
      .catch((err) =>
        setError(
          err instanceof Error
            ? err.message
            : "Could not load paused campaigns",
        ),
      );
  }, [accountId]);
  async function resume() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/whatsapp/campaigns/${campaignId}/resume`, {
        note: note.trim(),
      });
      toast.success(
        "Campaign resumed. Outreach health was re-checked by the server.",
      );
      onDone();
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Resume failed";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-line p-5">
          <div>
            <h2 className="text-lg font-bold">Resume outreach</h2>
            <p className="mt-1 text-sm text-muted">
              A fresh, non-red health check is required. Your note is saved to
              the audit log.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="grid gap-4 p-5">
          {error ? <DataState error={error} /> : null}
          {campaigns.length === 0 && !error ? (
            <p className="rounded-lg bg-slate-50 p-3 text-sm text-muted">
              There is no paused campaign to resume. Account outreach remains
              paused until a campaign can be resumed.
            </p>
          ) : null}
          <label className="grid gap-1.5 text-sm font-semibold">
            Paused campaign
            <select
              className="h-10 rounded-lg border border-line px-3 font-normal"
              value={campaignId}
              onChange={(e) => setCampaignId(e.target.value)}
            >
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1.5 text-sm font-semibold">
            Required resume note
            <textarea
              className="min-h-28 rounded-lg border border-line p-3 font-normal"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Why is it safe to resume?"
            />
          </label>
        </div>
        <div className="flex justify-end gap-2 border-t border-line p-5">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={resume}
            disabled={!campaignId || !note.trim() || busy}
          >
            {busy ? "Resuming…" : "Resume"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function WhatsappShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [accounts, setAccounts] = useState<WhatsappAccount[]>([]);
  const [accountId, setAccountId] = useState("");
  const [health, setHealth] = useState<OutreachHealth | null>(null);
  const [membership, setMembership] = useState<WorkspaceMembership | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resumeOpen, setResumeOpen] = useState(false);
  const account = accounts.find((item) => item.id === accountId) ?? null;
  const refreshHealth = useCallback(async () => {
    if (!accountId) {
      setHealth(null);
      return;
    }
    setHealth(
      await api.get<OutreachHealth>(
        `/whatsapp/accounts/${accountId}/outreach-health`,
      ),
    );
  }, [accountId]);
  useEffect(() => {
    Promise.all([
      api.get<WhatsappAccount[]>("/whatsapp/accounts"),
      getCurrentWorkspaceMembership(),
    ])
      .then(([rows, workspace]) => {
        setAccounts(rows);
        setAccountId(rows[0]?.id || "");
        setMembership(workspace);
      })
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Could not load WhatsApp",
        ),
      )
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    refreshHealth().catch((err) =>
      setError(
        err instanceof Error ? err.message : "Could not load outreach health",
      ),
    );
  }, [refreshHealth]);
  const nav = [
    ["/whatsapp/contacts", "Contacts"],
    ["/whatsapp/templates", "Templates"],
    ["/whatsapp/campaigns", "Campaigns"],
    ["/whatsapp/health", "Health"],
  ];
  const value = {
    account,
    accounts,
    setAccountId,
    health,
    refreshHealth,
    membership,
    outreachDisabled: health?.outreach_enabled === false,
  };
  return (
    <WorkspaceRoleProvider membership={membership}>
      <WhatsappContext.Provider value={value}>
        <div className="grid gap-5">
          <div className="flex flex-col gap-3 rounded-xl border border-line bg-white p-4 shadow-sm lg:flex-row lg:items-center lg:justify-between">
            <nav className="flex flex-wrap gap-1" aria-label="WhatsApp section">
              {nav.map(([href, label]) => (
                <Link
                  key={href}
                  href={href}
                  className={`rounded-lg px-3 py-2 text-sm font-semibold ${pathname.startsWith(href) ? "bg-emerald-50 text-emerald-800" : "text-muted hover:bg-slate-50 hover:text-ink"}`}
                >
                  {label}
                </Link>
              ))}
            </nav>
            <label className="flex items-center gap-2 text-sm font-semibold">
              Number
              <select
                className="h-10 min-w-52 rounded-lg border border-line bg-white px-3 font-normal"
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
              >
                {accounts.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_phone_number || item.phone_number_id}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <DataState loading={loading} error={error} />
          {!loading && !error && accounts.length === 0 ? (
            <div className="rounded-xl border border-dashed border-line bg-white p-8 text-center">
              <h2 className="font-bold">No WhatsApp account connected</h2>
              <p className="mt-2 text-sm text-muted">
                Connect a WhatsApp number from Accounts before using outreach.
              </p>
            </div>
          ) : null}
          {health?.outreach_enabled === false ? (
            <div className="flex gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <div>
                <p className="font-bold">
                  WhatsApp outreach is disabled globally
                </p>
                <p className="mt-1 text-sm">
                  Viewing data is still available. Sending, starting, and
                  resuming are disabled until a server administrator enables
                  outreach.
                </p>
              </div>
            </div>
          ) : null}
          {health?.outreach_paused ? (
            <div className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex gap-3">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
                <div>
                  <p className="font-bold">Outreach paused</p>
                  <p className="mt-1 text-sm" dir="auto">
                    Reason:{" "}
                    {health.outreach_paused_reason || "No reason provided"}
                  </p>
                </div>
              </div>
              {workspaceCan(membership, "run_campaigns") ? (
                <Button
                  variant="secondary"
                  className="gap-2"
                  onClick={() => setResumeOpen(true)}
                  disabled={health.outreach_enabled === false}
                >
                  <RefreshCw className="h-4 w-4" />
                  Resume with note
                </Button>
              ) : null}
            </div>
          ) : null}
          {account ? children : null}
        </div>
        {resumeOpen && account ? (
          <ResumeDialog
            accountId={account.id}
            onClose={() => setResumeOpen(false)}
            onDone={refreshHealth}
          />
        ) : null}
      </WhatsappContext.Provider>
    </WorkspaceRoleProvider>
  );
}
