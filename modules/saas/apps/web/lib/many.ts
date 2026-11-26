/**
 * Calls to the Many channel service through the SaaS API proxy (Phase 4B, decisions P1/P2).
 *
 * The browser never holds a Many token or a workspace id: it sends its session cookie to
 * `/api/v1/many/...` and the SaaS API forwards one allowlisted call. Failures are reduced to
 * a few kinds so every page shows the same states.
 */
import { api, ApiError } from "./api";

export type ManyFailure =
  | "forbidden" // the role cannot do this (the API said 403)
  | "not_available" // proxy flag off, or the path is not allowlisted (404)
  | "unavailable" // Many did not answer (502 MANY_UNAVAILABLE) or timed out
  | "session" // signed out (401)
  | "error"; // anything else

/** Pure: what kind of failure is this? */
export function manyFailureKind(error: unknown): ManyFailure {
  if (!(error instanceof ApiError)) return "error";
  if (error.status === 401) return "session";
  if (error.status === 403) return "forbidden";
  if (error.status === 404) return "not_available";
  if (error.code === "MANY_UNAVAILABLE" || error.status === 502) {
    return "unavailable";
  }
  if (error.status === 503 || error.status === 504) return "unavailable";
  return "error";
}

/** Plain words for each kind; never a raw status code. */
export const MANY_FAILURE_MESSAGE: Record<ManyFailure, string> = {
  forbidden: "Your role cannot open this page.",
  not_available: "This page is not available yet.",
  unavailable: "The channel service is not available right now. Try again.",
  session: "Your session has ended. Sign in again.",
  error: "Something went wrong. Try again.",
};

/** Platform-staff call to a Many route that is not workspace-scoped. */
export function manyStaff<T>(path: string): Promise<T> {
  return api<T>(`many/staff/${path.replace(/^\/+/, "")}`);
}

/** Organization-scoped call (the proxy sets the mapped workspace). */
export function manyOrg<T>(tenantId: string, path: string): Promise<T> {
  return api<T>(
    `many/orgs/${encodeURIComponent(tenantId)}/${path.replace(/^\/+/, "")}`,
  );
}

export interface ManyOverview {
  active_campaigns: number;
  triggers_today: number;
  messages_sent_today: number;
  failed_messages_today: number;
  new_leads_today: number;
}
