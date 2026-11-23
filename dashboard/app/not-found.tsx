import Link from "next/link";
import { Button } from "@/components/ui/Button";

export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-panel p-4">
      <div className="grid w-full max-w-lg gap-5 rounded-xl border border-line bg-white p-6 text-center shadow-xl shadow-slate-200/70">
        <div>
          <div className="mx-auto mb-4 h-1.5 w-16 rounded-full bg-accent" />
          <h1 className="text-2xl font-bold text-ink">Page not found</h1>
          <p className="mt-2 text-sm leading-6 text-muted">The page you are looking for does not exist or has moved.</p>
        </div>
        <div className="flex justify-center">
          <Link href="/overview"><Button type="button">Go to dashboard</Button></Link>
        </div>
      </div>
    </main>
  );
}
