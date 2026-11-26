"use client";

import { useState, type ReactNode } from "react";

import { manyRequest, type ManyScope } from "@/lib/many";
import { Button, ConfirmAction, Empty, StatusBadge } from "@/lib/ui";

import { AiSettingsPanel } from "./ai-settings-panel";
import type { ChannelNote } from "./connect-buttons";
import { DelegationPanel } from "./delegation-panel";
import {
  formatWhen,
  type AiSettingsFields,
  type FacebookPage,
  type WhatsappAccount,
} from "./types";

type Platform = "facebook" | "whatsapp";
type Account = (FacebookPage | WhatsappAccount) & AiSettingsFields;

function labelOf(platform: Platform, account: Account): string {
  if (platform === "facebook") {
    const page = account as FacebookPage;
    return page.page_name || page.page_id;
  }
  const number = account as WhatsappAccount;
  return number.display_phone_number || number.phone_number_id;
}

/**
 * One list of connected Facebook Pages or WhatsApp numbers with its actions.
 * Connect and disconnect need Admin (channels.connect, channels.disconnect), hard delete
 * needs Owner (channels.hard_delete). Everyone with channel access can read the list and the
 * AI settings; the API refuses the rest again.
 */
export function AccountSection({
  scope,
  platform,
  title,
  purpose,
  noun,
  accounts,
  emptyMessage,
  connectButton,
  canConnect,
  canDisconnect,
  canHardDelete,
  onChanged,
  onNote,
}: {
  scope: ManyScope;
  platform: Platform;
  title: string;
  purpose: string;
  /** "Page" or "number": used in confirmation texts. */
  noun: string;
  accounts: Account[];
  emptyMessage: string;
  connectButton: ReactNode;
  canConnect: boolean;
  canDisconnect: boolean;
  canHardDelete: boolean;
  onChanged: () => void;
  onNote: (note: ChannelNote) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function remove(account: Account, hard: boolean) {
    const id = String(account.id);
    setBusy(id);
    try {
      await manyRequest(
        scope,
        "DELETE",
        `${platform}/accounts/${encodeURIComponent(id)}${hard ? "/hard" : ""}`,
      );
      onNote({
        tone: "info",
        text: hard
          ? `${noun === "Page" ? "Facebook Page" : "WhatsApp number"} permanently deleted.`
          : `${noun === "Page" ? "Facebook Page" : "WhatsApp number"} disconnected.`,
      });
      onChanged();
    } catch (caught) {
      onNote({
        tone: "error",
        text:
          caught instanceof Error && caught.message
            ? caught.message
            : `Could not ${hard ? "delete" : "disconnect"} the ${noun.toLowerCase()}.`,
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section
      className="mc-section"
      data-testid={`section-${platform}`}
      aria-label={title}
    >
      <header className="mc-section-head">
        <div>
          <h2>{title}</h2>
          <p className="muted">{purpose}</p>
        </div>
        {canConnect && accounts.length > 0 && connectButton}
      </header>

      {accounts.length === 0 ? (
        <div data-testid={`empty-${platform}`}>
          <Empty>{emptyMessage}</Empty>
          {canConnect && <div className="mc-empty-action">{connectButton}</div>}
        </div>
      ) : (
        <ul className="mc-list">
          {accounts.map((account) => {
            const id = String(account.id);
            const label = labelOf(platform, account);
            const status = account.status || "connected";
            const connected = status === "connected";
            const open = expanded === id;
            return (
              <li
                key={id}
                className="mc-account"
                data-testid={`account-${platform}-${id}`}
              >
                <div className="mc-account-row">
                  <div className="mc-account-name">
                    <strong dir="auto">{label}</strong>
                    <span className="muted">
                      Last active:{" "}
                      {formatWhen(account.updated_at || account.created_at)}
                    </span>
                  </div>
                  <StatusBadge
                    value={status}
                    tone={connected ? "success" : "warning"}
                  />
                  <div className="mc-account-actions">
                    <Button
                      variant="quiet"
                      data-testid={`toggle-ai-${id}`}
                      aria-expanded={open}
                      onClick={() => setExpanded(open ? null : id)}
                    >
                      {account.ai_enabled ? "AI settings" : "Enable AI"}
                    </Button>
                    {canDisconnect && (
                      <ConfirmAction
                        testId={`disconnect-${id}`}
                        title={`Disconnect ${label}?`}
                        description={`The ${noun.toLowerCase()} stops receiving and sending messages here. You can connect it again later.`}
                        confirmLabel="Disconnect"
                        disabled={!connected || busy === id}
                        onConfirm={() => void remove(account, false)}
                      >
                        Disconnect
                      </ConfirmAction>
                    )}
                    {canHardDelete && (
                      <ConfirmAction
                        testId={`hard-delete-${id}`}
                        title={`Delete ${label} permanently?`}
                        description={`This permanently deletes the ${noun.toLowerCase()} and all its campaigns, messages and tokens. This cannot be undone.`}
                        confirmLabel="Delete permanently"
                        disabled={busy === id}
                        onConfirm={() => void remove(account, true)}
                      >
                        Delete permanently
                      </ConfirmAction>
                    )}
                    {!canConnect && !canDisconnect && !canHardDelete && (
                      <span className="muted">Read only</span>
                    )}
                  </div>
                </div>
                {open && (
                  <div className="mc-account-detail">
                    <AiSettingsPanel
                      scope={scope}
                      platform={platform}
                      accountId={id}
                      account={account}
                      canManage={canConnect}
                      onSaved={onChanged}
                      onNote={onNote}
                    />
                    <DelegationPanel
                      scope={scope}
                      platform={platform}
                      accountId={id}
                      canManage={canConnect}
                      onNote={onNote}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
