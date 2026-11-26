"use client";

/**
 * The shared frame of the WhatsApp outreach pages (Phase 4C): the section tabs, the number
 * (WhatsApp account) picker, the outreach banners and the resume-with-note dialog. It ports
 * `components/whatsapp/WhatsappShell.tsx` from the old dashboard. The layout puts it inside
 * a RoleGate, so it only runs for an Admin or Owner.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { manyRequest, ManyError } from "@/lib/many";
import { PageState, type PageStatus } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  Dialog,
  Field,
  LinkButton,
  Loading,
  Notice,
  Toast,
} from "@/lib/ui";
import type {
  OutreachHealth,
  WhatsappAccount,
  WhatsappCampaign,
} from "@/lib/whatsapp-types";

import "@/app/whatsapp-screen.css";

export type WhatsappContextValue = {
  tenantId: string;
  account: WhatsappAccount;
  accounts: WhatsappAccount[];
  setAccountId: (id: string) => void;
  health: OutreachHealth | null;
  healthStatus: PageStatus;
  refreshHealth: () => void;
  /** Outreach is switched off for the whole platform: viewing works, sending does not. */
  outreachDisabled: boolean;
  /** A short transient message (a success or a warning, never an error of an action). */
  notify: (message: string, tone?: "info" | "error") => void;
};

const WhatsappContext = createContext<WhatsappContextValue | null>(null);

export function useWhatsapp(): WhatsappContextValue {
  const value = useContext(WhatsappContext);
  if (!value) throw new Error("useWhatsapp must be used inside WhatsappShell");
  return value;
}

/** The plain message of a failed action (never a status code). */
export function actionMessage(caught: unknown, fallback: string): string {
  return caught instanceof ManyError && caught.message
    ? caught.message
    : fallback;
}

const SECTIONS = [
  { segment: "contacts", label: "Contacts" },
  { segment: "templates", label: "Templates" },
  { segment: "campaigns", label: "Campaigns" },
  { segment: "health", label: "Health" },
] as const;

export function accountLabel(account: WhatsappAccount): string {
  return account.display_phone_number || account.phone_number_id;
}

export function WhatsappShell({
  tenantId,
  children,
}: {
  tenantId: string;
  children: ReactNode;
}) {
  const pathname = usePathname() ?? "";
  const [toast, setToast] = useState<{
    message: string;
    tone: "info" | "error";
  } | null>(null);
  const notify = useCallback(
    (message: string, tone: "info" | "error" = "info") =>
      setToast({ message, tone }),
    [],
  );
  const { data, status } = useManyData<WhatsappAccount[]>(
    () =>
      manyRequest<WhatsappAccount[]>(
        { kind: "org", tenantId },
        "GET",
        "whatsapp/accounts",
      ),
    tenantId,
    {
      isEmpty: (rows) => rows.length === 0,
      emptyMessage:
        "No WhatsApp number is connected. Connect a number from Channels before using outreach.",
    },
  );
  const base = `/app/${tenantId}/whatsapp`;
  const channelsLink = (
    <LinkButton href={`/app/${tenantId}/channels`}>Open channels</LinkButton>
  );
  const shown: PageStatus =
    status.kind === "empty" ? { ...status, action: channelsLink } : status;
  return (
    <main className="wa-page" data-testid="whatsapp-shell">
      <nav
        className="wa-tabs"
        aria-label="WhatsApp section"
        data-testid="wa-tabs"
      >
        {SECTIONS.map((section) => {
          const href = `${base}/${section.segment}`;
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={section.segment}
              href={href}
              data-active={active ? "true" : "false"}
              data-testid={`wa-tab-${section.segment}`}
              aria-current={active ? "page" : undefined}
            >
              {section.label}
            </Link>
          );
        })}
      </nav>
      <PageState status={shown} homeHref={`/app/${tenantId}`}>
        {data && (
          <AccountScope
            key={tenantId}
            tenantId={tenantId}
            accounts={data}
            notify={notify}
          >
            {children}
          </AccountScope>
        )}
      </PageState>
      {toast && (
        <Toast
          message={toast.message}
          tone={toast.tone}
          onDismiss={() => setToast(null)}
        />
      )}
    </main>
  );
}

function AccountScope({
  tenantId,
  accounts,
  notify,
  children,
}: {
  tenantId: string;
  accounts: WhatsappAccount[];
  notify: WhatsappContextValue["notify"];
  children: ReactNode;
}) {
  const [accountId, setAccountId] = useState(accounts[0].id);
  const account = accounts.find((item) => item.id === accountId) ?? accounts[0];
  const [resumeOpen, setResumeOpen] = useState(false);
  const {
    data: health,
    status: healthStatus,
    reload,
  } = useManyData<OutreachHealth>(
    () =>
      manyRequest<OutreachHealth>(
        { kind: "org", tenantId },
        "GET",
        `whatsapp/accounts/${account.id}/outreach-health`,
      ),
    account.id,
  );
  const outreachDisabled = health?.outreach_enabled === false;
  const value = useMemo<WhatsappContextValue>(
    () => ({
      tenantId,
      account,
      accounts,
      setAccountId,
      health,
      healthStatus,
      refreshHealth: reload,
      outreachDisabled,
      notify,
    }),
    [
      tenantId,
      account,
      accounts,
      health,
      healthStatus,
      reload,
      outreachDisabled,
      notify,
    ],
  );
  return (
    <WhatsappContext.Provider value={value}>
      <div className="wa-account">
        <Field label="Number">
          {(control) => (
            <select
              {...control}
              dir="ltr"
              data-testid="wa-account-select"
              value={account.id}
              onChange={(event) => setAccountId(event.target.value)}
            >
              {accounts.map((item) => (
                <option key={item.id} value={item.id}>
                  {accountLabel(item)}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>
      {outreachDisabled && (
        <div className="wa-banner" data-tone="danger" data-testid="wa-disabled">
          <strong>WhatsApp outreach is disabled globally</strong>
          <p>
            Viewing data is still available. Sending, starting and resuming are
            disabled until a server administrator enables outreach.
          </p>
        </div>
      )}
      {health?.outreach_paused && (
        <div className="wa-banner" data-tone="warning" data-testid="wa-paused">
          <div>
            <strong>Outreach paused</strong>
            <p dir="auto">
              Reason: {health.outreach_paused_reason || "No reason provided"}
            </p>
          </div>
          <Button
            variant="quiet"
            data-testid="wa-resume-open"
            disabled={outreachDisabled}
            onClick={() => setResumeOpen(true)}
          >
            Resume with note
          </Button>
        </div>
      )}
      {children}
      <Dialog
        open={resumeOpen}
        onClose={() => setResumeOpen(false)}
        title="Resume outreach"
        className="wa-dialog"
        data-testid="wa-resume-dialog"
      >
        <ResumeForm
          tenantId={tenantId}
          accountId={account.id}
          onClose={() => setResumeOpen(false)}
          onDone={() => {
            notify(
              "Campaign resumed. Outreach health was re-checked by the server.",
            );
            reload();
          }}
        />
      </Dialog>
    </WhatsappContext.Provider>
  );
}

function ResumeForm({
  tenantId,
  accountId,
  onClose,
  onDone,
}: {
  tenantId: string;
  accountId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { data, status } = useManyData<WhatsappCampaign[]>(
    () =>
      manyRequest<WhatsappCampaign[]>(
        { kind: "org", tenantId },
        "GET",
        `whatsapp/campaigns?account_id=${accountId}&campaign_status=paused`,
      ),
    accountId,
  );
  const [picked, setPicked] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const campaignId = picked || data?.[0]?.id || "";
  async function resume() {
    setBusy(true);
    setError(null);
    try {
      await manyRequest(
        { kind: "org", tenantId },
        "POST",
        `whatsapp/campaigns/${campaignId}/resume`,
        { note: note.trim() },
      );
      onDone();
      onClose();
    } catch (caught) {
      setError(actionMessage(caught, "Could not resume the campaign."));
    } finally {
      setBusy(false);
    }
  }
  if (status.kind === "loading") return <Loading />;
  return (
    <div className="wa-form">
      <p className="muted">
        A fresh, non-red health check is required. Your note is saved to the
        audit log.
      </p>
      {error && <Notice message={error} tone="error" scope="item" />}
      {status.kind === "failed" ? (
        <Notice message="Could not load paused campaigns." tone="error" />
      ) : !data || data.length === 0 ? (
        <p className="muted" data-testid="wa-resume-none">
          There is no paused campaign to resume. Account outreach remains paused
          until a campaign can be resumed.
        </p>
      ) : (
        <>
          <Field label="Paused campaign">
            {(control) => (
              <select
                {...control}
                dir="auto"
                value={campaignId}
                onChange={(event) => setPicked(event.target.value)}
              >
                {data.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Required resume note" required>
            {(control) => (
              <textarea
                {...control}
                dir="auto"
                rows={3}
                value={note}
                placeholder="Why is it safe to resume?"
                onChange={(event) => setNote(event.target.value)}
              />
            )}
          </Field>
        </>
      )}
      <div className="action-row">
        <Button variant="quiet" onClick={onClose}>
          Cancel
        </Button>
        <Button
          data-testid="wa-resume-submit"
          onClick={resume}
          disabled={!campaignId || !note.trim() || busy}
        >
          {busy ? "Resuming…" : "Resume"}
        </Button>
      </div>
    </div>
  );
}
