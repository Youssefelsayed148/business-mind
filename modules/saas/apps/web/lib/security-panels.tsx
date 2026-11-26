"use client";

/**
 * Two-step verification and signed-in devices on the Account page (Phase 4E).
 * Both panels use the identity v2 routes; while the flag is off they answer 404 and the
 * panels render nothing, so the Account page is unchanged.
 */

import { useCallback, useEffect, useState, type FormEvent } from "react";

import * as api from "./api";
import { cleanCode, deviceLabel } from "./identity";
import {
  Button,
  Card,
  ConfirmAction,
  DataTable,
  Field,
  Loading,
  Notice,
  StatusBadge,
} from "./ui";

function messageOf(caught: unknown, fallback: string): string {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

function isNotFound(caught: unknown): boolean {
  return (caught as { status?: number }).status === 404;
}

export function MfaPanel() {
  const [status, setStatus] = useState<api.MfaStatus | null | "off">(null);
  const [setup, setSetup] = useState<{
    secret: string;
    otpauth_uri: string;
  } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await api.mfaStatus());
    } catch (caught) {
      if (isNotFound(caught)) setStatus("off");
      else setError(messageOf(caught, "Could not load verification status."));
    }
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setSetup(await api.mfaEnroll());
    } catch (caught) {
      setError(messageOf(caught, "Could not start the setup."));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    const clean = cleanCode(code);
    if (!clean) {
      setError("Enter the 6-digit code from your app.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const reply = await api.mfaConfirm(clean);
      setCodes(reply.recovery_codes);
      setSetup(null);
      setCode("");
      await load();
    } catch (caught) {
      setError(messageOf(caught, "That code is not correct."));
    } finally {
      setBusy(false);
    }
  }

  if (status === "off") return null;
  if (status === null && !error) return <Loading />;
  return (
    <Card title="Two-step verification" data-testid="mfa-panel">
      {error && <Notice message={error} tone="error" scope="item" />}
      {codes && (
        <div data-testid="mfa-recovery">
          <Notice
            scope="item"
            message="Save these recovery codes now. Each works once, and they are not shown again."
          />
          <ul dir="ltr" className="recovery-codes">
            {codes.map((value) => (
              <li key={value}>
                <code>{value}</code>
              </li>
            ))}
          </ul>
          <Button variant="quiet" onClick={() => setCodes(null)}>
            I saved them
          </Button>
        </div>
      )}
      {status && !codes && (
        <>
          {!status.available ? (
            <Notice
              scope="item"
              message="Two-step verification is not set up on this deployment."
            />
          ) : status.enrolled ? (
            <p data-testid="mfa-enrolled">
              <StatusBadge value="on" tone="success">
                On
              </StatusBadge>{" "}
              {status.recovery_codes_remaining} recovery{" "}
              {status.recovery_codes_remaining === 1 ? "code" : "codes"} left.
            </p>
          ) : setup ? (
            <form onSubmit={confirm} noValidate data-testid="mfa-setup">
              <p>
                Add this key to an authenticator app, then enter the 6-digit
                code it shows.
              </p>
              <p>
                Setup key: <code dir="ltr">{setup.secret}</code>
              </p>
              {setup.otpauth_uri.startsWith("otpauth://") && (
                <p>
                  <a href={setup.otpauth_uri}>
                    Open in an authenticator app on this device
                  </a>
                </p>
              )}
              <Field label="Code from your app">
                {(control) => (
                  <input
                    {...control}
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    dir="ltr"
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                  />
                )}
              </Field>
              <Button type="submit" disabled={busy}>
                Turn on
              </Button>
            </form>
          ) : (
            <>
              {status.required && (
                <Notice
                  scope="item"
                  message="Your role needs two-step verification. Set it up to keep access."
                />
              )}
              <p>
                <StatusBadge value="off" tone="neutral">
                  Off
                </StatusBadge>{" "}
                Add a second step when you sign in.
              </p>
              <Button
                onClick={() => void start()}
                disabled={busy}
                data-testid="mfa-start"
              >
                Set up two-step verification
              </Button>
            </>
          )}
        </>
      )}
    </Card>
  );
}

export function SessionsPanel() {
  const [rows, setRows] = useState<api.SessionRow[] | null | "off">(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.listSessions());
    } catch (caught) {
      if (isNotFound(caught)) setRows("off");
      else setError(messageOf(caught, "Could not load your devices."));
    }
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  async function signOutOthers() {
    setError(null);
    try {
      const reply = await api.revokeOtherSessions();
      setNotice(
        reply.revoked === 1
          ? "1 other session was signed out."
          : `${reply.revoked} other sessions were signed out.`,
      );
      await load();
    } catch (caught) {
      setError(messageOf(caught, "Could not sign out the other sessions."));
    }
  }

  if (rows === "off") return null;
  if (rows === null && !error) return <Loading />;
  const others = Array.isArray(rows)
    ? rows.filter((row) => !row.current).length
    : 0;
  return (
    <Card title="Signed-in devices" data-testid="sessions-panel">
      {error && <Notice message={error} tone="error" scope="item" />}
      {notice && <Notice message={notice} scope="item" />}
      {Array.isArray(rows) && (
        <>
          <DataTable
            caption="Signed-in devices"
            rows={rows}
            rowKey={(row) => row.id}
            columns={[
              {
                key: "device",
                header: "Device",
                cell: (row) => (
                  <>
                    {deviceLabel(row.user_agent)}{" "}
                    {row.current && (
                      <StatusBadge value="current" tone="info">
                        This device
                      </StatusBadge>
                    )}
                  </>
                ),
              },
              {
                key: "started",
                header: "Signed in",
                cell: (row) => new Date(row.created_at).toLocaleString(),
              },
              {
                key: "seen",
                header: "Last active",
                cell: (row) =>
                  row.last_seen_at
                    ? new Date(row.last_seen_at).toLocaleString()
                    : "Not recorded",
              },
            ]}
          />
          <ConfirmAction
            testId="sessions-revoke"
            title="Sign out other devices?"
            description="Every other session of your account will end. This device stays signed in."
            confirmLabel="Sign out others"
            disabled={others === 0}
            onConfirm={() => void signOutOthers()}
          >
            Sign out other devices
          </ConfirmAction>
        </>
      )}
    </Card>
  );
}
