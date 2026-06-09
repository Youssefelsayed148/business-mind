"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, LayoutDashboard, Link as LinkIcon, Megaphone, MessageSquare, UserPlus } from "lucide-react";
import { clearAccessToken } from "@/lib/auth";
import { Button } from "@/components/ui/Button";

const nav = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/accounts", label: "Accounts", icon: LinkIcon },
  { href: "/campaigns", label: "Campaigns", icon: Megaphone },
  { href: "/leads", label: "Leads", icon: UserPlus },
  { href: "/logs", label: "Logs", icon: Activity },
  { href: "/messages", label: "Messages", icon: MessageSquare },
];

export function Sidebar({ userEmail }: { userEmail?: string }) {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <aside className="sticky top-0 flex h-screen min-h-0 w-64 shrink-0 flex-col overflow-hidden bg-sidebar p-4 shadow-xl shadow-slate-900/10">
      <div className="mb-7 shrink-0 rounded-xl border border-emerald-300/15 bg-white/[0.03] p-4 shadow-lg shadow-emerald-950/20">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-emerald-300/25 bg-emerald-300/10 shadow-sm shadow-emerald-400/10">
            <Image src="/brand/robot.svg" alt="ManyOsirisChat logo" width={36} height={36} className="h-9 w-9" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-lg font-bold text-white">ManyOsirisChat</p>
            <p className="mt-1 truncate text-xs text-slate-400">{userEmail}</p>
          </div>
        </div>
      </div>
      <nav className="grid min-h-0 flex-1 gap-1.5 overflow-y-auto">
        {nav.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`group inline-flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold transition duration-150 ease-out ${active ? "bg-accent text-white shadow-sm shadow-emerald-950/30" : "text-slate-300 hover:bg-white/10 hover:text-white"}`}
            >
              <Icon className={`h-4 w-4 shrink-0 transition-colors ${active ? "text-white" : "text-slate-400 group-hover:text-white"}`} aria-hidden="true" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto shrink-0 pt-3">
        <Button
          type="button"
          variant="ghost"
          className="w-full justify-start border-white/10"
          onClick={() => {
            clearAccessToken();
            router.push("/login");
          }}
        >
          Logout
        </Button>
      </div>
    </aside>
  );
}
