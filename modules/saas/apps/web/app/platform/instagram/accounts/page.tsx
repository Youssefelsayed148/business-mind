"use client";

import { useEffect, useState } from "react";

import { ManyError, manyRequest } from "@/lib/many";
import {
  expiryStatus,
  formatDateTime,
  isConnected,
  safeOauthUrl,
} from "@/lib/many-instagram/helpers";
import { AiSettingsPanel } from "@/lib/many-instagram/ai-settings-panel";
import { staffGet, staffSend } from "@/lib/many-instagram/calls";
import { PostPicker } from "@/lib/many-instagram/post-picker";
import { SaasDelegationPanel } from "@/lib/many-instagram/saas-delegation-panel";
import type {
  AccountHealth,
  InstagramAccount,
} from "@/lib/many-instagram/types";
import { PageState } from "@/lib/page-state";
import { useSession } from "@/lib/session";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  Card,
  ConfirmAction,
  Field,
  Notice,
  PageHeader,
  StatusBadge,
} from "@/lib/ui";

import "@/app/instagram-screen.css";

const BASE = "/platform/instagram/accounts";
const EXPIRY_LABEL = {
  connected: "Connected",
  disconnected: "Disconnected",
  reconnect_required: "Reconnect required",
  expiring_soon: "Expiring soon",
} as const;
const EXPIRY_TONE = {
  connected: "success",
  disconnected: "neutral",
  reconnect_required: "danger",
  expiring_soon: "warning",
} as const;

type Banner = { text: string; tone: "info" | "error" };

function plain(caught: unknown, fallback: string) {
  return caught instanceof ManyError ? caught.message : fallback;
}

function accountName(account: InstagramAccount) {
  return account.username || account.ig_user_id;
}

function AccountDetails({
  account,
  onChanged,
}: {
  account: InstagramAccount;
  onChanged: () => void;
}) {
  const [health, setHealth] = useState<AccountHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [showPosts, setShowPosts] = useState(false);

  async function checkHealth() {
    setChecking(true);
    setHealthError(null);
    try {
      setHealth(
        await staffGet<AccountHealth>(
          `/instagram/accounts/${encodeURIComponent(account.id)}/health`,
        ),
      );
    } catch (caught) {
      setHealth(null);
      setHealthError(plain(caught, "Could not check the account health."));
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="ig-details" data-testid={`ig-details-${account.id}`}>
      <section className="ig-subpanel" aria-label="Health">
        <header className="ig-subpanel-head">
          <div>
            <h3>Health</h3>
            <p className="muted">
              Checks that Many still holds a token for this account.
            </p>
          </div>
          <Button
            variant="quiet"
            disabled={checking}
            data-testid="ig-health-check"
            onClick={() => void checkHealth()}
          >
            {checking ? "Checking..." : "Check health"}
          </Button>
        </header>
        {health && (
          <p data-testid="ig-health-result">
            <StatusBadge
              value={health.status}
              tone={health.has_token ? "success" : "danger"}
            />{" "}
            {health.has_token
              ? "A token is stored."
              : "No token is stored. Reconnect the account."}
          </p>
        )}
        {healthError && (
          <Notice tone="error" message={healthError} scope="item" />
        )}
      </section>

      <section className="ig-subpanel" aria-label="Recent posts">
        <header className="ig-subpanel-head">
          <div>
            <h3>Recent posts</h3>
            <p className="muted">
              The posts Instagram returns for this account.
            </p>
          </div>
          <Button
            variant="quiet"
            aria-expanded={showPosts}
            data-testid="ig-posts-toggle"
            onClick={() => setShowPosts((value) => !value)}
          >
            {showPosts ? "Hide posts" : "Show posts"}
          </Button>
        </header>
        {showPosts && <PostPicker accountId={account.id} />}
      </section>

      <AiSettingsPanel account={account} onSaved={onChanged} />
      <SaasDelegationPanel accountId={account.id} />
    </div>
  );
}

/**
 * Instagram accounts for platform staff. Reading, AI settings, disconnect and the SaaS
 * delegation use the staff scope. Connect, reconnect and permanent delete are workspace
 * routes: they need an organization, chosen in the picker.
 */
export default function InstagramAccountsPage() {
  const { staffOrganizations, staffOrganizationsError } = useSession();
  const { data, status, reload } = useManyData(
    () => staffGet<InstagramAccount[]>("/instagram/accounts"),
    "accounts",
    {
      isEmpty: (rows) => rows.length === 0,
      emptyMessage:
        "No Instagram accounts are connected. Choose an organization and connect one.",
    },
  );
  const [tenantId, setTenantId] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<Banner | null>(null);

  // The OAuth return: Many sends the browser back with ?connected, ?reconnected or ?error.
  useEffect(() => {
    const timer = setTimeout(() => {
      const params = new URLSearchParams(window.location.search);
      const connected = params.get("connected") === "true";
      const reconnected = params.get("reconnected") === "true";
      const failed = params.get("error") === "oauth_failed";
      if (!connected && !reconnected && !failed) return;
      window.history.replaceState({}, "", BASE);
      if (failed) {
        setBanner({
          text: "Could not connect the Instagram account. Try again.",
          tone: "error",
        });
      } else {
        setBanner({
          text: connected
            ? "Instagram account connected."
            : "Instagram account reconnected.",
          tone: "info",
        });
        reload();
      }
    }, 0);
    return () => clearTimeout(timer);
  }, [reload]);

  const org = tenantId ? { kind: "org" as const, tenantId } : null;

  async function startOauth(
    key: string,
    method: "GET" | "POST",
    path: string,
    failure: string,
  ) {
    if (!org) return;
    setBusy(key);
    setBanner(null);
    try {
      const reply = await manyRequest<{ oauth_url?: string }>(
        org,
        method,
        path,
      );
      const target = safeOauthUrl(reply?.oauth_url);
      if (!target) throw new Error("bad address");
      window.location.href = target;
    } catch (caught) {
      setBanner({ text: plain(caught, failure), tone: "error" });
      setBusy(null);
    }
  }

  async function disconnect(account: InstagramAccount) {
    setBusy(`disconnect-${account.id}`);
    setBanner(null);
    try {
      await staffSend(
        "DELETE",
        `/instagram/accounts/${encodeURIComponent(account.id)}`,
      );
      setBanner({ text: "Account disconnected.", tone: "info" });
      reload();
    } catch (caught) {
      setBanner({
        text: plain(caught, "Could not disconnect the account."),
        tone: "error",
      });
    } finally {
      setBusy(null);
    }
  }

  async function hardDelete(account: InstagramAccount) {
    if (!org) return;
    setBusy(`delete-${account.id}`);
    setBanner(null);
    try {
      await manyRequest(
        org,
        "DELETE",
        `/instagram/accounts/${encodeURIComponent(account.id)}/hard`,
      );
      setBanner({ text: "Account permanently deleted.", tone: "info" });
      if (expandedId === account.id) setExpandedId(null);
      reload();
    } catch (caught) {
      setBanner({
        text: plain(caught, "Could not delete the account."),
        tone: "error",
      });
    } finally {
      setBusy(null);
    }
  }

  const orgs = staffOrganizations ?? [];

  return (
    <div className="ig-page" data-testid="ig-accounts">
      <PageHeader
        title="Instagram accounts"
        purpose="Connected Instagram accounts, their health and AI settings. Platform staff only."
        actions={
          <Button
            disabled={!org || busy === "connect"}
            data-testid="ig-connect"
            onClick={() =>
              void startOauth(
                "connect",
                "GET",
                "/meta/connect/start",
                "Could not start the Instagram connection.",
              )
            }
          >
            {busy === "connect" ? "Connecting..." : "Connect Instagram"}
          </Button>
        }
      />

      <Card title="Organization" data-testid="ig-org-card">
        <Field
          label="Organization for connect, reconnect and permanent delete"
          hint={
            org
              ? "These three actions run inside the chosen organization."
              : "Choose an organization to enable connect, reconnect and permanent delete."
          }
        >
          {(control) => (
            <select
              {...control}
              data-testid="ig-org-select"
              value={tenantId}
              onChange={(event) => setTenantId(event.target.value)}
            >
              <option value="">Choose an organization</option>
              {orgs.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        {staffOrganizationsError && (
          <Notice tone="error" message={staffOrganizationsError} scope="item" />
        )}
      </Card>

      {banner && (
        <Notice tone={banner.tone} message={banner.text} scope="item" />
      )}

      <PageState status={status} homeHref="/platform">
        <ul className="ig-list" data-testid="ig-account-list">
          {(data ?? []).map((account) => {
            const state = expiryStatus(account);
            const connected = isConnected(account);
            const open = expandedId === account.id;
            const name = accountName(account);
            return (
              <li
                key={account.id}
                className="ig-row"
                data-testid={`ig-account-${account.id}`}
              >
                <div className="ig-row-main">
                  <div className="ig-row-title">
                    <strong dir="auto">{name}</strong>
                    <StatusBadge
                      value={state}
                      tone={EXPIRY_TONE[state]}
                      data-testid="ig-account-state"
                    >
                      {EXPIRY_LABEL[state]}
                    </StatusBadge>
                  </div>
                  <p className="muted">
                    {account.account_type || "Business"} &middot; Token expires{" "}
                    {account.expires_at
                      ? formatDateTime(account.expires_at)
                      : "n/a"}{" "}
                    &middot; Last active{" "}
                    {formatDateTime(account.updated_at || account.created_at)}
                  </p>
                </div>
                <div className="action-row">
                  <Button
                    variant="quiet"
                    aria-expanded={open}
                    data-testid={`ig-toggle-${account.id}`}
                    onClick={() => setExpandedId(open ? null : account.id)}
                  >
                    {open
                      ? "Hide details"
                      : account.ai_enabled
                        ? "AI settings"
                        : "Details"}
                  </Button>
                  <Button
                    variant="quiet"
                    disabled={
                      !org || connected || busy === `reconnect-${account.id}`
                    }
                    title={
                      !org
                        ? "Choose an organization first"
                        : connected
                          ? "Only a disconnected account needs this"
                          : undefined
                    }
                    data-testid={`ig-reconnect-${account.id}`}
                    onClick={() =>
                      void startOauth(
                        `reconnect-${account.id}`,
                        "POST",
                        `/instagram/accounts/${encodeURIComponent(account.id)}/reconnect`,
                        "Could not start the reconnect.",
                      )
                    }
                  >
                    {busy === `reconnect-${account.id}`
                      ? "Redirecting..."
                      : "Reconnect"}
                  </Button>
                  <ConfirmAction
                    title={`Disconnect ${name}?`}
                    description="Active campaigns on this account are paused. You can reconnect it later."
                    confirmLabel="Disconnect"
                    disabled={!connected || busy === `disconnect-${account.id}`}
                    testId={`ig-disconnect-${account.id}`}
                    onConfirm={() => void disconnect(account)}
                  >
                    Disconnect
                  </ConfirmAction>
                  <ConfirmAction
                    title="Delete account permanently?"
                    description={`This permanently deletes ${name} and all its campaigns, messages and tokens. It cannot be undone.${
                      org ? "" : " Choose an organization first."
                    }`}
                    confirmLabel="Delete permanently"
                    disabled={!org || busy === `delete-${account.id}`}
                    testId={`ig-delete-${account.id}`}
                    onConfirm={() => void hardDelete(account)}
                  >
                    Delete permanently
                  </ConfirmAction>
                </div>
                {open && (
                  <AccountDetails account={account} onChanged={reload} />
                )}
              </li>
            );
          })}
        </ul>
      </PageState>
    </div>
  );
}
