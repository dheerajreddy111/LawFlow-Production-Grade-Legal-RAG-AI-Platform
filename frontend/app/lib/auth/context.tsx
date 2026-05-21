"use client";

/**
 * AuthProvider + useAuth.
 *
 * Single source of truth for the React side of the auth state. The token
 * store in client.ts mirrors `session.accessToken` so non-React callers
 * (streaming fetch in lib/api.ts) still work.
 *
 * Bootstrap on mount: hit /auth/refresh once. The refresh cookie travels
 * automatically; success → we know who the user is. Failure → unauth.
 * This is also how F5 / fresh-tab navigation re-hydrates the session.
 */

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  API_BASE,
  apiFetch,
  refreshSession,
  setAccessToken,
  setOnUnauthorized,
  subscribeToRefresh,
} from "./client";
import { clearRoleHint, setRoleHint } from "./cookies";
import type {
  AuthResponse,
  AuthSession,
  LoginFields,
  SignupFields,
  UserRole,
} from "./types";

type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  status: AuthStatus;
  session: AuthSession | null;
  /** Convenience role getter — null when unauthenticated. */
  role: UserRole | null;
  isAdmin: boolean;
  login: (fields: LoginFields) => Promise<AuthSession>;
  signup: (fields: SignupFields) => Promise<AuthSession>;
  adminLogin: (fields: LoginFields) => Promise<AuthSession>;
  logout: () => Promise<void>;
  /** Force an immediate refresh (e.g., after a 401 the caller observed). */
  refresh: () => Promise<AuthSession | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function authResponseToSession(body: AuthResponse): AuthSession {
  return {
    user: body.user,
    accessToken: body.access_token,
    expiresAtMs: Date.now() + body.expires_in * 1000,
  };
}

export class AuthError extends Error {
  status: number;
  /** Backend's {"detail": "..."} message — mirrors `message` for ergonomics. */
  detail: string;
  constructor(status: number, message: string) {
    super(message);
    this.name = "AuthError";
    this.status = status;
    this.detail = message;
  }
}

async function postAuth(
  path: string,
  body: object,
  signal?: AbortSignal
): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "include",
    signal,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail =
      (data && typeof data === "object" && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : null) ?? `Request failed (${res.status})`;
    throw new AuthError(res.status, detail);
  }
  return data as AuthResponse;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const mounted = useRef(false);

  // Centralised "apply a fresh session" — keeps the in-memory token store,
  // the role-hint cookie, and React state in lock-step.
  const applySession = useCallback((body: AuthResponse | null) => {
    if (body === null) {
      setAccessToken(null);
      clearRoleHint();
      setSession(null);
      setStatus("anonymous");
      return;
    }
    const next = authResponseToSession(body);
    setAccessToken(next.accessToken);
    setRoleHint(next.user.role);
    setSession(next);
    setStatus("authenticated");
  }, []);

  // Bootstrap once on mount. We don't show a flash of unauthenticated UI —
  // status stays "loading" until the refresh attempt resolves.
  useEffect(() => {
    if (mounted.current) return;
    mounted.current = true;
    let cancelled = false;
    (async () => {
      const body = await refreshSession();
      if (cancelled) return;
      applySession(body);
    })();
    return () => {
      cancelled = true;
    };
  }, [applySession]);

  // Mirror future refresh outcomes (from apiFetch retries) into React state.
  useEffect(() => {
    return subscribeToRefresh((body) => {
      if (body) applySession(body);
    });
  }, [applySession]);

  // Hard-401 hook — wired so apiFetch can clear us when refresh fails too.
  useEffect(() => {
    setOnUnauthorized(() => applySession(null));
    return () => setOnUnauthorized(null);
  }, [applySession]);

  const login = useCallback(
    async (fields: LoginFields) => {
      const body = await postAuth("/api/v1/auth/login", fields);
      applySession(body);
      return authResponseToSession(body);
    },
    [applySession]
  );

  const signup = useCallback(
    async (fields: SignupFields) => {
      const body = await postAuth("/api/v1/auth/signup", fields);
      applySession(body);
      return authResponseToSession(body);
    },
    [applySession]
  );

  const adminLogin = useCallback(
    async (fields: LoginFields) => {
      const body = await postAuth("/api/v1/auth/admin-login", fields);
      applySession(body);
      return authResponseToSession(body);
    },
    [applySession]
  );

  const logout = useCallback(async () => {
    try {
      await apiFetch("/api/v1/auth/logout", {
        method: "POST",
        skipRefresh: true,
      });
    } catch {
      // Even if the server is unreachable we still want a clean local logout
      // — leaving stale tokens behind is worse than a missed revocation.
    }
    applySession(null);
  }, [applySession]);

  const refresh = useCallback(async () => {
    const body = await refreshSession();
    applySession(body);
    if (!body) return null;
    return authResponseToSession(body);
  }, [applySession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      session,
      role: session?.user.role ?? null,
      isAdmin: session?.user.role === "admin",
      login,
      signup,
      adminLogin,
      logout,
      refresh,
    }),
    [status, session, login, signup, adminLogin, logout, refresh]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
