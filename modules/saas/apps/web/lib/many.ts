/**
 * Calls to the Many channel service through the SaaS API proxy (Phase 4B, decisions P1/P2).
 *
 * The browser never holds a Many token or a workspace id: it sends its session cookie to
 * `/api/v1/many/...` and the SaaS API forwards one allowlisted call. Failures are reduced to
 * a few kinds so every page shows the same states.
 */
import { api, ApiError, csrfHeader, rememberCsrfFrom } from "./api";

export type ManyFailure =
  | "forbidden" // the role cannot do this (the API said 403)
  | "not_available" // proxy flag off, or the path is not allowlisted (404)
  | "unavailable" // Many did not answer (502 MANY_UNAVAILABLE) or timed out
  | "session" // signed out (401)
  | "error"; // anything else

/** A failed call to Many through the proxy: the status and a plain message. */
export class ManyError extends Error {
  readonly status: number;
  readonly code: string | null;
  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.name = "ManyError";
    this.status = status;
    this.code = code;
  }
}

/**
 * Pure: the best plain message in an error body. Many answers `{detail: ...}` (a string, an
 * object with message or code, or a list of field problems); the SaaS proxy answers
 * `{error: {code, message}}`. Never returns a raw status code.
 */
export function manyMessage(payload: unknown, status: number): string {
  const fallback =
    status === 409
      ? "This conflicts with the current state."
      : status === 422 || status === 400
        ? "Some fields need attention."
        : status === 429
          ? "Too many requests. Wait a moment and try again."
          : status >= 500
            ? "The channel service had a problem. Try again later."
            : "The request could not be completed.";
  if (!payload || typeof payload !== "object") return fallback;
  const body = payload as Record<string, unknown>;
  const detail = body.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>;
    if (typeof d.message === "string" && d.message) return d.message;
    if (typeof d.code === "string" && d.code)
      return d.code.replaceAll("_", " ");
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) =>
        item && typeof item === "object"
          ? String(
              (item as Record<string, unknown>).msg ??
                (item as Record<string, unknown>).message ??
                "",
            )
          : String(item),
      )
      .filter(Boolean);
    if (parts.length) return parts.join(", ");
  }
  const error = body.error;
  if (error && typeof error === "object") {
    const message = (error as Record<string, unknown>).message;
    if (typeof message === "string" && message) return message;
  }
  if (typeof body.message === "string" && body.message) return body.message;
  return fallback;
}

/** Pure: what kind of failure is this? */
export function manyFailureKind(error: unknown): ManyFailure {
  if (error instanceof ManyError) {
    if (error.status === 401) return "session";
    if (error.status === 403) return "forbidden";
    if (error.status === 404) return "not_available";
    if (error.code === "MANY_UNAVAILABLE" || error.status >= 502) {
      return "unavailable";
    }
    return "error";
  }
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

export type ManyScope = { kind: "org"; tenantId: string } | { kind: "staff" };

/** The proxy URL for a Many path (a leading slash is dropped; the query stays in `path`). */
export function manyUrl(scope: ManyScope, path: string): string {
  const clean = path.replace(/^\/+/, "");
  return scope.kind === "org"
    ? `/api/v1/many/orgs/${encodeURIComponent(scope.tenantId)}/${clean}`
    : `/api/v1/many/staff/${clean}`;
}

/**
 * One call to Many through the SaaS proxy, with the session cookie and CSRF header. `body`
 * may be JSON-able or a FormData (file upload; the browser sets the boundary). Failures throw
 * ManyError with a plain message; 401 also signs the person out like every other call.
 */
export async function manyRequest<T>(
  scope: ManyScope,
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET") Object.assign(headers, csrfHeader());
  let response: Response;
  try {
    response = await fetch(manyUrl(scope, path), {
      method,
      headers,
      credentials: "same-origin",
      body: payload,
    });
  } catch {
    throw new ManyError(
      502,
      MANY_FAILURE_MESSAGE.unavailable,
      "MANY_UNAVAILABLE",
    );
  }
  rememberCsrfFrom(response.headers);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("session-expired"));
    }
    const code =
      parsed && typeof parsed === "object"
        ? (((parsed as { error?: { code?: unknown } }).error?.code as
            string | undefined) ?? null)
        : null;
    throw new ManyError(
      response.status,
      manyMessage(parsed, response.status),
      code,
    );
  }
  return parsed as T;
}

export interface ManyOverview {
  active_campaigns: number;
  triggers_today: number;
  messages_sent_today: number;
  failed_messages_today: number;
  new_leads_today: number;
}
