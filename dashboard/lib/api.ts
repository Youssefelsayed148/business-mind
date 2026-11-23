const DEFAULT_DEVELOPMENT_API_URL = "http://localhost:8000";

function normalizeApiUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

function resolveApiBaseUrl(): string {
  const configuredUrl = process.env.NEXT_PUBLIC_API_URL?.trim();

  if (configuredUrl) {
    return normalizeApiUrl(configuredUrl);
  }

  if (process.env.NODE_ENV !== "production") {
    console.error(
      `NEXT_PUBLIC_API_URL is missing. Falling back to ${DEFAULT_DEVELOPMENT_API_URL} for development.`,
    );
    return DEFAULT_DEVELOPMENT_API_URL;
  }

  console.error("NEXT_PUBLIC_API_URL is missing. Backend API requests cannot be sent.");
  return "";
}

const API_URL = resolveApiBaseUrl();

type RequestOptions = {
  body?: unknown;
  headers?: HeadersInit;
  authenticated?: boolean;
  redirectOnUnauthorized?: boolean;
  logPath?: string;
};

export type ApiErrorCode =
  | "bad_request"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "rate_limited"
  | "server_error"
  | "network_error"
  | "unknown";

export class ApiError extends Error {
  status: number;
  code: ApiErrorCode;
  friendlyMessage: string;
  technicalMessage?: string;

  constructor(status: number, friendlyMessage: string, code: ApiErrorCode = "unknown", technicalMessage?: string) {
    super(friendlyMessage);
    this.status = status;
    this.code = code;
    this.friendlyMessage = friendlyMessage;
    this.technicalMessage = technicalMessage;
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("access_token");
}

function redirectToLogin(path: string) {
  if (typeof window !== "undefined" && window.location.pathname !== "/login" && path !== "/auth/login") {
    window.localStorage.removeItem("access_token");
    window.location.href = "/login";
  }
}

async function extractError(response: Response): Promise<string> {
  const fallback = `${response.status} ${response.statusText}`.trim();
  try {
    const data: unknown = await response.json();
    if (!data || typeof data !== "object") return fallback;
    const body = data as Record<string, unknown>;
    if (typeof body.detail === "string") return body.detail;
    if (body.detail && typeof body.detail === "object" && !Array.isArray(body.detail)) {
      const detail = body.detail as Record<string, unknown>;
      if (typeof detail.message === "string") return detail.message;
      if (typeof detail.code === "string") return detail.code.replaceAll("_", " ");
    }
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((item: unknown) => {
          if (item && typeof item === "object") {
            const entry = item as Record<string, unknown>;
            return entry.msg || entry.message || JSON.stringify(entry);
          }
          return String(item);
        })
        .join(", ");
    }
    if (typeof body.message === "string") return body.message;
  } catch {
    return fallback;
  }
  return fallback;
}

function normalizeHttpError(status: number, backendMessage: string): ApiError {
  if (status === 401) return new ApiError(status, "Your session expired. Please log in again.", "unauthorized", backendMessage);
  if (status === 403) return new ApiError(status, "You do not have permission to perform this action.", "forbidden", backendMessage);
  if (status === 404) return new ApiError(status, backendMessage || "The requested item was not found.", "not_found", backendMessage);
  if (status === 409) return new ApiError(status, backendMessage || "This action conflicts with the current state.", "conflict", backendMessage);
  if (status === 429) return new ApiError(status, backendMessage || "Too many requests. Please wait a moment and try again.", "rate_limited", backendMessage);
  if (status >= 500) return new ApiError(status, "Server error. Please try again later.", "server_error", backendMessage);
  if (status === 400 || status === 422) return new ApiError(status, backendMessage || "Some fields need attention.", "bad_request", backendMessage);
  return new ApiError(status, backendMessage || "Request failed. Please try again.", "unknown", backendMessage);
}

function logApiError(error: ApiError, path: string) {
  if (process.env.NODE_ENV !== "production") {
    console.error("API request failed", {
      path,
      status: error.status,
      code: error.code,
      message: error.message,
      technicalMessage: error.technicalMessage,
    });
  }
}

// --- Workspace-scoped routes -----------------------------------------------
// WhatsApp/Facebook and Instagram OAuth mutations use workspace membership.
// Other Instagram routes retain their existing authorization. The workspace is
// resolved once per page load from /workspaces/me, preferring the workspace
// with slug "default" and falling back to the first membership.

export type WorkspaceMembership = {
  id: string;
  name: string;
  slug: string;
  role: string;
};

const WORKSPACE_SCOPED_PREFIXES = ["/whatsapp/", "/facebook/"];

function isWorkspaceScopedPath(path: string): boolean {
  return path === "/meta/connect/start" || /^\/instagram\/accounts\/[^/]+\/reconnect$/.test(path) || WORKSPACE_SCOPED_PREFIXES.some(
    (prefix) => path === prefix.slice(0, -1) || path.startsWith(prefix),
  );
}

let workspaceMembershipPromise: Promise<WorkspaceMembership | null> | null = null;

export function getCurrentWorkspaceMembership(): Promise<WorkspaceMembership | null> {
  if (!workspaceMembershipPromise) {
    workspaceMembershipPromise = request<WorkspaceMembership[]>("GET", "/workspaces/me")
      .then((memberships) => {
        if (!Array.isArray(memberships) || memberships.length === 0) return null;
        const defaultWorkspace = memberships.find((m) => m.slug === "default");
        return defaultWorkspace ?? memberships[0];
      })
      .catch(() => {
        // Allow a retry on the next request instead of caching the failure.
        workspaceMembershipPromise = null;
        return null;
      });
  }
  return workspaceMembershipPromise;
}

async function resolveWorkspaceId(): Promise<string | null> {
  return (await getCurrentWorkspaceMembership())?.id ?? null;
}

async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  if (!API_URL) {
    throw new ApiError(0, "Cannot reach the server. Check your connection.", "network_error", "NEXT_PUBLIC_API_URL is required in production.");
  }
  if (!path.startsWith("/")) {
    throw new Error(`API paths must start with "/": ${path}`);
  }

  const token = getToken();
  const headers = new Headers(options.headers);
  let body: BodyInit | undefined;

  if (options.body instanceof URLSearchParams || options.body instanceof FormData) {
    body = options.body;
  } else if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }

  if (token && options.authenticated !== false) headers.set("Authorization", `Bearer ${token}`);

  if (isWorkspaceScopedPath(path)) {
    const workspaceId = await resolveWorkspaceId();
    if (workspaceId) headers.set("X-Workspace-Id", workspaceId);
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body,
    });
  } catch (err) {
    const error = new ApiError(0, "Cannot reach the server. Check your connection.", "network_error", err instanceof Error ? err.message : String(err));
    logApiError(error, options.logPath || path);
    throw error;
  }

  if (response.status === 401) {
    const backendMessage = await extractError(response);
    const error = path === "/auth/login"
      ? new ApiError(401, backendMessage || "Incorrect email or password", "unauthorized", backendMessage)
      : normalizeHttpError(401, backendMessage);
    logApiError(error, options.logPath || path);
    if (options.redirectOnUnauthorized !== false) redirectToLogin(path);
    throw error;
  }

  if (!response.ok) {
    const error = normalizeHttpError(response.status, await extractError(response));
    logApiError(error, options.logPath || path);
    throw error;
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown, headers?: HeadersInit) =>
    request<T>("POST", path, { body, headers }),
  publicPost: <T>(path: string, body?: unknown) =>
    request<T>("POST", path, {
      body,
      authenticated: false,
      redirectOnUnauthorized: false,
      logPath: "/public/whatsapp/opt-in/{token}",
    }),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

export const apiBaseUrl = API_URL;
