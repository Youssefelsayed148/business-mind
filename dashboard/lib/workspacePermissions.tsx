"use client";

import { createContext, useContext } from "react";
import type { WorkspaceMembership } from "./api";

const workspacePermissions: Record<string, string[]> = {
  owner: ["manage_contacts", "manage_templates", "run_campaigns"],
  admin: ["manage_contacts", "manage_templates", "run_campaigns"],
  operator: [],
  viewer: [],
};

const WorkspaceContext = createContext<WorkspaceMembership | null>(null);

export function WorkspaceRoleProvider({
  membership,
  children,
}: {
  membership: WorkspaceMembership | null;
  children: React.ReactNode;
}) {
  return (
    <WorkspaceContext.Provider value={membership}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspaceMembership() {
  return useContext(WorkspaceContext);
}
export function workspaceCan(
  membership: WorkspaceMembership | null,
  permission: string,
) {
  return (
    workspacePermissions[
      (membership?.role || "viewer").toLowerCase()
    ]?.includes(permission) ?? false
  );
}
export function useWorkspaceCan(permission: string) {
  return workspaceCan(useWorkspaceMembership(), permission);
}
export function useWorkspaceAdmin() {
  return ["owner", "admin"].includes(
    (useWorkspaceMembership()?.role || "viewer").toLowerCase(),
  );
}
