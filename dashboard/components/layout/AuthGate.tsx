"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getAccessToken, getMe } from "@/lib/auth";
import type { User } from "@/lib/types";
import { Sidebar } from "./Sidebar";
import { PermissionProvider } from "@/lib/permissions";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    getMe()
      .then(setUser)
      .finally(() => setReady(true));
  }, [router]);

  if (!ready) {
    return <main className="min-h-screen bg-panel p-6 text-sm font-medium text-muted">Loading dashboard...</main>;
  }

  return (
    <div className="flex h-screen min-h-0 max-w-[100vw] overflow-hidden bg-panel">
      <Sidebar userEmail={user?.email} />
      <PermissionProvider user={user}>
        <main className="h-screen min-w-0 flex-1 overflow-y-auto overflow-x-hidden p-4 md:p-6 lg:p-8">
          <div className="mx-auto min-w-0 w-full max-w-full overflow-x-hidden">{children}</div>
        </main>
      </PermissionProvider>
    </div>
  );
}
