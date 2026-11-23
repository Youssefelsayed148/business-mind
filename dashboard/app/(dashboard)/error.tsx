"use client";

import Link from "next/link";
import { useEffect } from "react";
import { Button } from "@/components/ui/Button";

export default function DashboardError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-[70vh] items-center justify-center p-4">
      <div className="grid w-full max-w-lg gap-5 rounded-xl border border-line bg-white p-6 text-center shadow-xl shadow-slate-200/70">
        <div>
          <div className="mx-auto mb-4 h-1.5 w-16 rounded-full bg-danger" />
          <h1 className="text-2xl font-bold text-ink">Something went wrong</h1>
          <p className="mt-2 text-sm leading-6 text-muted">This dashboard page failed to load. Try again, or return to the overview.</p>
        </div>
        {process.env.NODE_ENV !== "production" ? <pre className="max-h-40 overflow-auto rounded-lg border border-red-100 bg-red-50 p-3 text-left font-mono text-xs text-red-800">{error.message}</pre> : null}
        <div className="flex flex-wrap justify-center gap-2">
          <Button type="button" onClick={reset}>Retry</Button>
          <Link href="/overview"><Button type="button" variant="secondary">Go to dashboard</Button></Link>
        </div>
      </div>
    </div>
  );
}
