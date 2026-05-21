/**
 * Low-level authenticated fetch.
 *
 * Responsibilities, in order:
 *   1. Resolve the current access token (from the in-memory token store).
 *   2. Attach `Authorization: Bearer <jwt>` and `credentials: include` so the
 *      backend can also read the refresh cookie when needed.
 *   3. On 401, attempt ONE silent refresh via POST /auth/refresh. The refresh
 *      cookie travels automatically because it is httpOnly + same-origin /
 *      explicit credentials. If the refresh succeeds, replay the original
 *      request once. If it fails, surface the 401 to the caller and trigger
 *      the registered onUnauthorized hook (AuthProvider clears state).
 *
 * Concurrency: refresh attempts are deduplicated through a module-level
 * promise so a flurry of simultaneous 401s only triggers one /auth/refresh
 * round-trip — preventing the classic refresh storm and avoiding a race
 * where two retries rotate each other's tokens.
 */

import type { AuthResponse } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// ── Token store ────────────────────────────────────────────────────────────
// Held in module scope so non-React callers (lib/api.ts streaming) can read
// it without piping through a hook. The AuthContext is still the source of
// truth — it pushes updates here on every login/refresh/logout.

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

// ── Refresh deduplication + listeners ──────────────────────────────────────

type RefreshListener = (result: AuthResponse | null) => void;
let refreshInFlight: Promise<AuthResponse | null> | null = null;
const refreshListeners = new Set<RefreshListener>();
let onUnauthorized: (() => void) | null = null;

/** AuthProvider registers this so we can clear React state on hard-401. */
export function setOnUnauthorized(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

/** Allow other modules (AuthProvider) to mirror refresh outcomes. */
export function subscribeToRefresh(fn: RefreshListener): () => void {
  refreshListeners.add(fn);
  return () => refreshListeners.delete(fn);
}

/**
 * Attempt one /auth/refresh, deduplicated. Returns the new AuthResponse on
 * success, or null on failure. Listeners are notified either way.
 */
export async function refreshSession(): Promise<AuthResponse | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) return null;
      const body = (await res.json()) as AuthResponse;
      setAccessToken(body.access_token);
      return body;
    } catch {
      return null;
    } finally {
      // Notify listeners *after* token is set; clear in-flight last so any
      // racing await sees the resolved value, not a re-trigger.
    }
  })();

  const result = await refreshInFlight;
  refreshInFlight = null;
  for (const fn of refreshListeners) {
    try {
      fn(result);
    } catch {
      // Listener errors must never break refresh — auth state is critical.
    }
  }
  return result;
}

// ── Authenticated fetch ────────────────────────────────────────────────────

export interface ApiFetchOptions extends RequestInit {
  /** Don't add Authorization header even if a token is present. */
  skipAuth?: boolean;
  /** Don't attempt 401 refresh/retry (used internally on /auth/* calls). */
  skipRefresh?: boolean;
}

function withAuthHeaders(init: ApiFetchOptions): RequestInit {
  const headers = new Headers(init.headers);
  if (!init.skipAuth) {
    const tok = getAccessToken();
    if (tok) headers.set("Authorization", `Bearer ${tok}`);
  }
  if (init.body && !headers.has("Content-Type") && typeof init.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  return {
    ...init,
    headers,
    credentials: init.credentials ?? "include",
  };
}

/**
 * Authenticated fetch with one transparent refresh-on-401 retry.
 *
 * The caller still gets a regular Response and is responsible for parsing
 * the body. Errors below the HTTP layer (DNS, offline) propagate normally
 * so callers can render a network-error state.
 */
export async function apiFetch(
  path: string,
  init: ApiFetchOptions = {}
): Promise<Response> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const res = await fetch(url, withAuthHeaders(init));

  if (res.status !== 401 || init.skipRefresh) return res;

  // The first response is consumed only on success path; for retry the
  // server already discarded it on its side. We don't need to .body.cancel().
  const refreshed = await refreshSession();
  if (!refreshed) {
    if (onUnauthorized) onUnauthorized();
    return res; // surface the original 401 to the caller
  }
  return fetch(url, withAuthHeaders({ ...init, skipRefresh: true }));
}

// ── Streaming variant (SSE) ────────────────────────────────────────────────

/**
 * Streaming fetch with the same refresh-on-401 semantics as apiFetch.
 * Returns the Response so the caller can drive a ReadableStream reader.
 * On hard-401 we still surface the response (status=401) so the caller
 * can render an auth-required state — we do NOT silently swallow it.
 */
// ── Change password ───────────────────────────────────────────────────────

export interface ChangePasswordError extends Error {
  status: number;
  detail: string;
}

/**
 * POST /api/v1/auth/change-password.
 *
 * On success the server revokes every active refresh token, so the caller
 * should follow up with a fresh /auth/login (or relog) — otherwise the
 * next /auth/refresh will fail. Returns nothing; throws on non-2xx with a
 * `status` + `detail` payload the UI can render.
 */
export async function changePassword(input: {
  current_password: string;
  new_password: string;
}): Promise<void> {
  const res = await apiFetch("/api/v1/auth/change-password", {
    method: "POST",
    body: JSON.stringify(input),
    skipRefresh: true, // a 401 here is the "wrong current password" path
  });
  if (res.ok) return;
  let detail = `Request failed (HTTP ${res.status})`;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    /* non-JSON */
  }
  const err = new Error(detail) as ChangePasswordError;
  err.status = res.status;
  err.detail = detail;
  throw err;
}

export async function apiStreamFetch(
  path: string,
  init: ApiFetchOptions = {}
): Promise<Response> {
  // Pre-flight refresh if we have no token at all — avoids a guaranteed 401
  // on every fresh tab load. Cheap; the request is deduplicated above.
  if (!getAccessToken() && !init.skipAuth) {
    await refreshSession();
  }
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const res = await fetch(url, withAuthHeaders(init));
  if (res.status !== 401 || init.skipRefresh) return res;

  const refreshed = await refreshSession();
  if (!refreshed) {
    if (onUnauthorized) onUnauthorized();
    return res;
  }
  return fetch(url, withAuthHeaders({ ...init, skipRefresh: true }));
}
