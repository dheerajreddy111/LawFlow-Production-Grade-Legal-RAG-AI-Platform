/**
 * Next.js 16 Proxy (formerly Middleware) — lightweight optimistic routing.
 *
 * Reads the non-credential `lf_role` cookie set by the client AuthProvider.
 * The backend remains the source of truth: every protected API endpoint
 * verifies the JWT bearer token + DB row independently. This file does
 * one thing only — short-circuit obvious wrong-place navigations so users
 * don't see admin chrome flash before the client-side redirect kicks in.
 *
 * Gates:
 *   • /admin and /admin/* (EXCEPT /admin/login)
 *       → if no `lf_role=admin` cookie, redirect to /admin/login
 *   • /login, /signup
 *       → if any `lf_role` cookie is set, redirect to the appropriate
 *         landing page (/admin for admins, / for users)
 *   • /admin/login
 *       → if already an admin, redirect to /admin
 *
 * Forged cookies do not grant access — the admin page itself re-verifies
 * via /auth/me and the API blocks unauthorised calls at 401/403.
 */

import { NextRequest, NextResponse } from "next/server";

const ROLE_COOKIE = "lf_role";

function pathStartsWith(path: string, prefix: string): boolean {
  return path === prefix || path.startsWith(`${prefix}/`);
}

export function proxy(req: NextRequest): NextResponse {
  const { pathname } = req.nextUrl;
  const role = req.cookies.get(ROLE_COOKIE)?.value;
  const isAdmin = role === "admin";
  const isAuthed = role === "admin" || role === "user";

  // /admin/login is always reachable so admins can sign in.
  const onAdminLogin = pathname === "/admin/login";
  const onUserAuth = pathname === "/login" || pathname === "/signup";

  // Gate /admin/* (except /admin/login itself).
  if (pathStartsWith(pathname, "/admin") && !onAdminLogin && !isAdmin) {
    const url = req.nextUrl.clone();
    url.pathname = "/admin/login";
    url.search = ""; // don't leak the failed deep-link path
    return NextResponse.redirect(url);
  }

  // Send already-authed users away from auth pages so they don't see a
  // login form while logged in.
  if (onAdminLogin && isAdmin) {
    const url = req.nextUrl.clone();
    url.pathname = "/admin";
    return NextResponse.redirect(url);
  }
  if (onUserAuth && isAuthed) {
    const url = req.nextUrl.clone();
    url.pathname = isAdmin ? "/admin" : "/";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

// Match auth + admin routes only — chat / health / static assets pass through.
export const config = {
  matcher: ["/admin", "/admin/:path*", "/login", "/signup"],
};
