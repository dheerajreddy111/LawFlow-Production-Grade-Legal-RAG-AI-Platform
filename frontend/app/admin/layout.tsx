"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { AdminSidebar } from "../components/admin/AdminSidebar";
import { AdminTopBar } from "../components/admin/AdminTopBar";
import { ToastProvider } from "../components/admin/Toast";
import { useAuth } from "../lib/auth/context";

/**
 * Layout for the entire admin route group.
 *
 * - /admin/login renders bare (its own AuthShell handles chrome), so we
 *   skip the sidebar + top bar on that path.
 * - For everything else, we re-verify admin role client-side. proxy.ts
 *   already gates this at the edge via the lf_role cookie, but the
 *   cookie is a hint, not a credential — the in-process /auth/refresh
 *   bootstrap is the authoritative check.
 */
export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { status, session, isAdmin } = useAuth();

  // /admin/login: skip the admin chrome and the gate entirely.
  const isAdminLogin = pathname === "/admin/login";

  useEffect(() => {
    if (isAdminLogin) return;
    if (status === "loading") return;
    if (!session) router.replace("/admin/login");
    else if (!isAdmin) router.replace("/");
  }, [isAdminLogin, status, session, isAdmin, router]);

  if (isAdminLogin) {
    return <>{children}</>;
  }

  if (status === "loading" || !isAdmin) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#ECEEF3]">
        <div className="flex items-center gap-2 text-[12px] text-slate-500">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#C9892A]" />
          <span>Verifying admin session…</span>
        </div>
      </div>
    );
  }

  return (
    <ToastProvider>
      <div className="flex h-screen overflow-hidden bg-[#F5F6FA]">
        <AdminSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <AdminTopBar />
          <main className="flex-1 overflow-y-auto">{children}</main>
        </div>
      </div>
    </ToastProvider>
  );
}
