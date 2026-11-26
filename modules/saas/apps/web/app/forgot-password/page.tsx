"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import * as api from "@/lib/api";
import { Button, Field, Notice } from "@/lib/ui";
import "@/app/auth-screen.css";

/**
 * Ask for a password reset link (Phase 4E). The API gives the same answer for every address,
 * so this page never says whether an account exists. While identity v2 is off the API answers
 * 404 and the page says the feature is not available.
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!email.trim()) {
      setError("Enter your email address.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setDone(await api.passwordResetRequest(email.trim()));
    } catch (caught) {
      const status = (caught as { status?: number }).status;
      setError(
        status === 404
          ? "Password reset is not available here. Contact your administrator."
          : status === 429
            ? "Too many requests. Please try again later."
            : "We could not send the request. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <h1>Reset your password</h1>
      <p className="page-purpose">
        Enter your email address. If an account exists, we send a link that is
        valid for a short time.
      </p>
      {done ? (
        <div data-testid="reset-requested">
          <Notice message={done} scope="item" />
        </div>
      ) : (
        <form onSubmit={onSubmit} noValidate>
          <Field label="Email" error={error ?? undefined}>
            {(control) => (
              <input
                {...control}
                type="email"
                name="email"
                autoComplete="email"
                dir="ltr"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            )}
          </Field>
          <Button type="submit" disabled={busy}>
            {busy ? "Sending..." : "Send reset link"}
          </Button>
        </form>
      )}
      <p className="auth-footer">
        <Link href="/login">Back to sign in</Link>
      </p>
    </main>
  );
}
