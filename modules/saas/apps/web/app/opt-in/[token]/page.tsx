"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Icon } from "@/lib/icons";
import { manyMessage } from "@/lib/many";
import { cleanOptInPhone, safeChatUrl } from "@/lib/opt-in";
import { Button, Field, Notice } from "@/lib/ui";

import "@/app/opt-in-screen.css";

/**
 * Public WhatsApp opt-in (Phase 4C, same address as the old dashboard). No login: the page
 * posts the customer's number to the SaaS API, which checks and limits it and forwards it to
 * Many. Permission is not active until the customer sends the prepared WhatsApp message.
 */
export default function PublicOptInPage() {
  const { token } = useParams<{ token: string }>();
  const [phone, setPhone] = useState("");
  const [chatUrl, setChatUrl] = useState<string | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cleaned = cleanOptInPhone(phone);
    if (!cleaned) {
      setError("Enter your number with the country code, starting with +.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/many/public/whatsapp/opt-in/${encodeURIComponent(token)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "omit",
          body: JSON.stringify({ phone: cleaned }),
        },
      );
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setError(
          response.status === 404
            ? "This link is not valid any more. Ask the business for a new one."
            : response.status === 429
              ? "Too many requests. Please try again later."
              : manyMessage(payload, response.status),
        );
        return;
      }
      setChatUrl(
        safeChatUrl(
          (payload as { click_to_chat_url?: unknown } | null)
            ?.click_to_chat_url,
        ),
      );
    } catch {
      setError(
        "We could not reach the service. Check your connection and try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="optin-page" id="main">
      <section className="optin-card ui-card">
        <span className="optin-mark" aria-hidden="true">
          <Icon name="conversations" size={22} />
        </span>
        <h1>Confirm WhatsApp messages</h1>
        {chatUrl === undefined ? (
          <form onSubmit={submit} noValidate data-testid="optin-form">
            <p className="muted">
              Enter your WhatsApp number. You will then open WhatsApp and send a
              prepared confirmation message to the business.
            </p>
            <Field
              label="WhatsApp number"
              hint="Include the country code and the leading + sign."
              error={error ?? undefined}
              required
            >
              {(props) => (
                <input
                  {...props}
                  type="tel"
                  autoComplete="tel"
                  inputMode="tel"
                  dir="ltr"
                  placeholder="+15551234567"
                  value={phone}
                  onChange={(event) => setPhone(event.target.value)}
                />
              )}
            </Field>
            <Button type="submit" disabled={submitting || !phone.trim()}>
              {submitting ? "Preparing..." : "Continue"}
            </Button>
          </form>
        ) : (
          <div data-testid="optin-done">
            <Notice
              scope="item"
              message="One more step. Open WhatsApp using the button below, then send the prepared message. Permission is not active until you send it."
            />
            {chatUrl ? (
              <a
                className="link-button"
                data-variant="primary"
                href={chatUrl}
                target="_blank"
                rel="noreferrer"
              >
                Open WhatsApp and send
              </a>
            ) : (
              <Notice
                scope="item"
                message="The request was recorded, but WhatsApp could not be opened automatically. Contact the business for its WhatsApp number and send the requested opt-in keyword."
              />
            )}
          </div>
        )}
      </section>
    </main>
  );
}
