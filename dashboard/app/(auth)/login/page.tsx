"use client";

import { FormEvent, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { login, setAccessToken } from "@/lib/auth";
import { useToast } from "@/components/ToastProvider";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await login(email, password);
      setAccessToken(result.access_token);
      router.push("/overview");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-panel p-4">
      <form onSubmit={onSubmit} className="grid w-full max-w-md gap-5 rounded-2xl border border-line bg-white p-8 shadow-xl shadow-slate-200/70">
        <div>
          <div className="mb-5 flex items-center gap-3">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-emerald-200 bg-mint shadow-sm shadow-emerald-900/10">
              <Image src="/brand/robot.svg" alt="ManyOsirisChat logo" width={40} height={40} className="h-10 w-10" priority />
            </span>
            <div className="min-w-0">
              <h1 className="text-2xl font-bold text-ink">ManyOsirisChat</h1>
              <div className="mt-1 h-1 w-16 rounded-full bg-accent" />
            </div>
          </div>
          <p className="mt-2 text-sm text-muted">Log in with your internal admin account.</p>
        </div>
        <Field label="Email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        <Field label="Password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        {error ? <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-danger">{error}</p> : null}
        <Button type="submit" disabled={loading}>{loading ? "Logging in..." : "Login"}</Button>
      </form>
    </main>
  );
}
