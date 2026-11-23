"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Field, Select } from "@/components/ui/Field";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

export function MockConnect({ onConnected }: { onConnected: () => void }) {
  const [form, setForm] = useState({
    ig_user_id: "",
    username: "",
    account_type: "BUSINESS",
    access_token: "",
    expires_at: "",
  });
  const [message, setMessage] = useState<string | null>(null);
  const toast = useToast();

  if (process.env.NEXT_PUBLIC_APP_ENV !== "development") return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    try {
      await api.post("/meta/connect/mock", {
        ...form,
        expires_at: form.expires_at || null,
      });
      setMessage("Mock account connected.");
      toast.success("Mock account connected.");
      onConnected();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to connect mock account");
    }
  }

  return (
    <Panel>
      <div className="mb-4">
        <h2 className="text-lg font-bold text-ink">Mock connect account</h2>
        <p className="mt-1 text-sm text-muted">Connect a development Instagram account without changing production OAuth behavior.</p>
      </div>
      <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
        <Field label="IG user ID" value={form.ig_user_id} onChange={(e) => setForm({ ...form, ig_user_id: e.target.value })} required />
        <Field label="Username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
        <Select label="Account type" value={form.account_type} onChange={(e) => setForm({ ...form, account_type: e.target.value })}>
          <option value="BUSINESS">Business</option>
          <option value="CREATOR">Creator</option>
        </Select>
        <Field label="Expires at" type="datetime-local" value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })} />
        <div className="md:col-span-2">
          <Field label="Access token" value={form.access_token} onChange={(e) => setForm({ ...form, access_token: e.target.value })} required />
        </div>
        <div className="flex items-center gap-3 md:col-span-2">
          <Button type="submit">Connect mock account</Button>
          {message ? <span className="rounded-full border border-emerald-200 bg-mint px-3 py-1 text-sm font-semibold text-emerald-700">{message}</span> : null}
        </div>
      </form>
    </Panel>
  );
}
