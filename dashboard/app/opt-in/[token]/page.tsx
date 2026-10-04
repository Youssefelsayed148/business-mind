"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { ArrowRight, CheckCircle2, MessageCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";

type OptInResponse = {
  accepted: boolean;
  message: string;
  click_to_chat_url?: string | null;
};

export default function PublicOptInPage() {
  const { token } = useParams<{ token: string }>();
  const [phone, setPhone] = useState("");
  const [result, setResult] = useState<OptInResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const response = await api.publicPost<OptInResponse>(
        `/public/whatsapp/opt-in/${encodeURIComponent(token)}`,
        { phone: phone.trim() },
      );
      setResult(response);
    } catch {
      setError(
        "We could not process this request. Check the phone number or ask the business for a new link.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-slate-50 p-4">
      <section className="w-full max-w-lg rounded-2xl border border-line bg-white p-6 shadow-xl shadow-slate-200/60 sm:p-8">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-100 text-emerald-700">
          <MessageCircle aria-hidden="true" className="h-6 w-6" />
        </div>
        <h1 className="mt-5 text-2xl font-bold text-ink">
          Confirm WhatsApp messages
        </h1>
        {!result ? (
          <form className="mt-5 grid gap-4" onSubmit={submit}>
            <p className="text-sm leading-6 text-muted">
              Enter your WhatsApp number. You will then open WhatsApp and send a
              prepared confirmation message to the business.
            </p>
            <label className="grid gap-1.5 text-sm font-semibold text-ink">
              WhatsApp number
              <input
                required
                type="tel"
                autoComplete="tel"
                inputMode="tel"
                placeholder="+15551234567"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                className="h-11 rounded-lg border border-line px-3 font-normal outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
              />
              <span className="text-xs font-normal text-muted">
                Include the country code and leading + sign.
              </span>
            </label>
            {error ? (
              <p
                role="alert"
                className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
              >
                {error}
              </p>
            ) : null}
            <Button type="submit" disabled={submitting || !phone.trim()}>
              {submitting ? "Preparing…" : "Continue"}
            </Button>
          </form>
        ) : (
          <div className="mt-5 grid gap-4">
            <div className="flex gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-950">
              <CheckCircle2
                aria-hidden="true"
                className="mt-0.5 h-5 w-5 shrink-0"
              />
              <div>
                <p className="font-bold">One more step</p>
                <p className="mt-1 text-sm leading-6">
                  Open WhatsApp using the button below, then send the prepared
                  message. Permission is not active until you send it.
                </p>
              </div>
            </div>
            {result.click_to_chat_url ? (
              <a
                href={result.click_to_chat_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-white hover:bg-accentHover"
              >
                Open WhatsApp and send{" "}
                <ArrowRight aria-hidden="true" className="h-4 w-4" />
              </a>
            ) : (
              <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                The request was recorded, but WhatsApp could not be opened
                automatically. Contact the business for its WhatsApp number and
                send the requested opt-in keyword.
              </p>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
