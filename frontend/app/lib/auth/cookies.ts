/**
 * Role-hint cookie (`lf_role`).
 *
 * This is a *non-credential* cookie that proxy.ts uses to make optimistic
 * routing decisions (gate /admin/* without a network round-trip). It is
 * NOT trusted by the API — every backend call is still verified against
 * the JWT bearer token + database. If a user forges this cookie they'll
 * be allowed past proxy.ts but the admin pages themselves re-check via
 * /auth/me before showing privileged UI.
 *
 * Set with path=/ and SameSite=Lax so it travels alongside normal
 * navigations. Not httpOnly because the client-side AuthProvider needs
 * to set and clear it; the cookie does not grant access on its own.
 */

import type { UserRole } from "./types";

export const ROLE_COOKIE = "lf_role";

export function setRoleHint(role: UserRole): void {
  if (typeof document === "undefined") return;
  const maxAge = 60 * 60 * 24 * 14; // 14d, same as refresh token lifetime
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:";
  document.cookie = [
    `${ROLE_COOKIE}=${encodeURIComponent(role)}`,
    "Path=/",
    `Max-Age=${maxAge}`,
    "SameSite=Lax",
    secure ? "Secure" : "",
  ]
    .filter(Boolean)
    .join("; ");
}

export function clearRoleHint(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${ROLE_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}

export function readRoleHint(): UserRole | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${ROLE_COOKIE}=`));
  if (!match) return null;
  const raw = decodeURIComponent(match.slice(ROLE_COOKIE.length + 1));
  return raw === "admin" || raw === "user" ? raw : null;
}
