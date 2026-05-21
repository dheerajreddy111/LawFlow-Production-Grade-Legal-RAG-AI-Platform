"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { KeyRound, Menu } from "lucide-react";
import { useState } from "react";

import { useAuth } from "../../lib/auth/context";
import { ThemeToggle } from "../ThemeToggle";
import { AdminMobileDrawer } from "./AdminMobileDrawer";

export function AdminTopBar() {
  const { session, logout } = useAuth();
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);

  async function onSignOut() {
    await logout();
    router.replace("/admin/login");
  }

  return (
    <header className="relative flex h-12 shrink-0 items-center gap-2 border-b border-slate-200/70 bg-white px-3 sm:gap-3 sm:px-6">
      {/* Mobile hamburger — visible below lg breakpoint. Opens the side drawer
          which mirrors AdminSidebar's items so mobile operators have the same
          navigation surface as desktop. */}
      <button
        type="button"
        onClick={() => setDrawerOpen(true)}
        aria-label="Open admin navigation"
        aria-expanded={drawerOpen}
        className="-ml-1 inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-50 hover:text-[#0A1628] lg:hidden"
      >
        <Menu className="h-4 w-4" aria-hidden />
      </button>

      <Link href="/admin/overview" className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-[#0A1628] ring-1 ring-[#C9892A]/35">
          <ScalesIcon />
        </span>
        <span className="font-display text-[14px] font-semibold tracking-tight text-[#0A1628]">
          LawFlow
        </span>
        <span className="hidden rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-semibold tracking-[0.16em] text-slate-600 sm:inline-block">
          ADMIN
        </span>
      </Link>

      <div className="flex-1" />

      <Link
        href="/"
        className="hidden items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] text-slate-500 transition-colors hover:text-[#0A1628] md:inline-flex"
      >
        Research workspace
        <span aria-hidden>↗</span>
      </Link>

      <ThemeToggle size="sm" />

      <Link
        href="/admin/settings/password"
        title="Change password"
        className="hidden h-7 items-center gap-1.5 rounded-md border border-slate-200 px-2 text-[11.5px] font-medium text-slate-600 transition-colors hover:border-slate-300 hover:text-[#0A1628] sm:inline-flex"
      >
        <KeyRound className="h-3 w-3" aria-hidden />
        Password
      </Link>

      <div className="flex items-center gap-2">
        <span className="hidden max-w-[180px] truncate text-[11.5px] text-slate-500 md:inline">
          {session?.user.email}
        </span>
        <button
          onClick={onSignOut}
          className="rounded-md border border-slate-200 px-2.5 py-1 text-[11.5px] font-medium text-slate-600 transition-colors hover:border-slate-300 hover:text-[#0A1628]"
        >
          Sign out
        </button>
      </div>

      <AdminMobileDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </header>
  );
}

function ScalesIcon() {
  return (
    <svg
      className="h-3.5 w-3.5 text-[#C9892A]"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.8}
        d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3"
      />
    </svg>
  );
}
