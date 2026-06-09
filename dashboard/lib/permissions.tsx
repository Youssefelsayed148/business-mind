"use client";

import { createContext, useContext } from "react";
import type { User } from "./types";

const permissions: Record<string, string[]> = {
  owner: ["manage_campaigns", "delete_campaigns", "manage_accounts", "disconnect_accounts", "view_audit_logs", "retry_messages"],
  admin: ["manage_campaigns", "delete_campaigns", "manage_accounts", "disconnect_accounts", "view_audit_logs", "retry_messages"],
  operator: ["manage_campaigns", "view_audit_logs"],
  viewer: ["view_audit_logs"],
};

const PermissionContext = createContext<User | null>(null);

export function PermissionProvider({ user, children }: { user: User | null; children: React.ReactNode }) {
  return <PermissionContext.Provider value={user}>{children}</PermissionContext.Provider>;
}

export function useCurrentUser() {
  return useContext(PermissionContext);
}

export function normalizeRole(role?: string | null) {
  const value = (role || "viewer").toLowerCase();
  return value === "user" ? "viewer" : value;
}

export function userCan(user: User | null, permission: string) {
  return permissions[normalizeRole(user?.role)]?.includes(permission) ?? false;
}

export function useCan(permission: string) {
  return userCan(useCurrentUser(), permission);
}
