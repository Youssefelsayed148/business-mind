"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import * as api from "@/lib/api";
import { passwordProblem } from "@/lib/identity";
import { PasswordField } from "@/lib/password-field";
import { Button, Field, Notice } from "@/lib/ui";
import "@/app/auth-screen.css";

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const problem = passwordProblem(password, confirm);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.passwordResetConfirm(token, password);
      setDone(true);
    } catch (caught) {
      const status = (caught as { status?: number }).status;
      setError(
        status === 404
          ? "Password reset is not available here. Contact your administrator."
          : caught instanceof Error
            ? caught.message
            : "We could not reset the password.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <main className="auth-page">
        <h1>Choose a new password</h1>
        <Notice
          tone="error"
          scope="item"
          message="This link is missing its reset token. Ask for a new link."
        />
        <p className="auth-footer">
          <Link href="/forgot-password">Ask for a new link</Link>
        </p>
      </main>
    );
  }
  return (
    <main className="auth-page">
      <h1>Choose a new password</h1>
      {done ? (
        <div data-testid="reset-done">
          <Notice
            scope="item"
            message="Your password was changed. Every other session was signed out."
          />
          <p className="auth-footer">
            <Link href="/login">Sign in</Link>
          </p>
        </div>
      ) : (
        <form onSubmit={onSubmit} noValidate>
          <Field label="New password" error={error ?? undefined}>
            {(control) => (
              <PasswordField
                {...control}
                type="password"
                name="new-password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            )}
          </Field>
          <Field label="Confirm new password">
            {(control) => (
              <PasswordField
                {...control}
                type="password"
                name="confirm-password"
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
              />
            )}
          </Field>
          <Button type="submit" disabled={busy}>
            {busy ? "Saving..." : "Change password"}
          </Button>
        </form>
      )}
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<main className="eyebrow">Loading...</main>}>
      <ResetForm />
    </Suspense>
  );
}
