"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "../lib/auth/context";
import { ThemeToggle } from "./ThemeToggle";

/** Two-letter initial(s) from a name or email. Falls back to "L". */
function initials(input: string | null | undefined): string {
  if (!input) return "L";
  const trimmed = input.trim();
  if (trimmed.includes("@")) {
    return trimmed[0]!.toUpperCase();
  }
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "L";
  if (parts.length === 1) return parts[0]![0]!.toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

/**
 * Header element used in the main chat nav. Renders:
 *   - "Sign in / Sign up" when anonymous
 *   - An avatar + popover menu (Profile, Admin Console for admins, Sign out)
 *     when authenticated
 *
 * Styled to match the dark navy nav strip from app/page.tsx — gold accents,
 * small ring, subtle hover.
 */
export function UserMenu() {
  const { status, session, isAdmin, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (status === "loading") {
    return (
      <div className="h-8 w-8 animate-pulse rounded-full bg-white/10" aria-hidden />
    );
  }

  if (status === "anonymous" || !session) {
    return (
      <div className="flex items-center gap-2">
        <Link
          href="/login"
          className="hidden rounded-lg px-3 py-1.5 text-[12px] text-slate-300 ring-1 ring-white/10 transition-all hover:bg-white/[0.04] hover:text-white sm:inline-flex"
        >
          Sign in
        </Link>
        <Link
          href="/signup"
          className="inline-flex items-center gap-1.5 rounded-lg bg-[#C9892A]/15 px-3 py-1.5 text-[12px] font-semibold text-[#D8A849] ring-1 ring-[#C9892A]/40 transition-all hover:bg-[#C9892A]/25 hover:text-[#E8B860]"
        >
          Create account
        </Link>
      </div>
    );
  }

  const label = session.user.full_name?.trim() || session.user.email;
  const initial = initials(session.user.full_name || session.user.email);

  return (
    <div className="relative" ref={wrapperRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="group flex items-center gap-2 rounded-full pl-1 pr-2.5 py-1 ring-1 ring-white/10 transition-all hover:bg-white/[0.04] hover:ring-[#C9892A]/35"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-[#C9892A]/35 to-[#C9892A]/10 text-[11.5px] font-bold text-[#D8A849] ring-1 ring-[#C9892A]/45">
          {initial}
        </span>
        <span className="hidden text-[12px] font-medium text-slate-200 sm:inline-block">
          {label}
        </span>
        {isAdmin && (
          <span className="hidden rounded bg-[#C9892A]/20 px-1.5 py-0.5 text-[9px] font-bold tracking-[0.18em] text-[#D8A849] ring-1 ring-[#C9892A]/40 sm:inline-block">
            ADMIN
          </span>
        )}
        <svg
          className={`h-3 w-3 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.2}
          aria-hidden
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          className="lf-rise absolute right-0 top-[calc(100%+8px)] z-30 w-64 rounded-xl border border-slate-200/70 bg-white p-1.5 shadow-[0_18px_40px_-18px_rgba(10,22,40,0.35)] ring-1 ring-black/[0.02]"
        >
          <div className="px-3 py-2.5">
            <p className="font-display text-[13px] font-semibold leading-tight text-[#0A1628]">
              {label}
            </p>
            <p className="mt-0.5 text-[11.5px] text-slate-500">
              {session.user.email}
            </p>
            <div className="mt-2 inline-flex items-center gap-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-[0.16em] text-slate-600">
              {isAdmin ? (
                <span className="text-[#9E6A0E]">Administrator</span>
              ) : (
                <span>Member</span>
              )}
            </div>
          </div>
          <div className="my-1 h-px bg-slate-100" />
          {isAdmin && (
            <Link
              href="/admin"
              role="menuitem"
              className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[12.5px] text-[#0A1628] transition-colors hover:bg-[#C9892A]/8"
              onClick={() => setOpen(false)}
            >
              <span className="flex h-6 w-6 items-center justify-center rounded bg-[#0A1628] text-[#D8A849]">
                <ShieldIcon />
              </span>
              Admin Console
            </Link>
          )}
          <Link
            href="/"
            role="menuitem"
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[12.5px] text-slate-700 transition-colors hover:bg-slate-50"
            onClick={() => setOpen(false)}
          >
            <span className="flex h-6 w-6 items-center justify-center rounded bg-slate-100 text-slate-600">
              <ChatIcon />
            </span>
            Research workspace
          </Link>
          <Link
            href="/settings/password"
            role="menuitem"
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[12.5px] text-slate-700 transition-colors hover:bg-slate-50"
            onClick={() => setOpen(false)}
          >
            <span className="flex h-6 w-6 items-center justify-center rounded bg-slate-100 text-slate-600">
              <KeyIcon />
            </span>
            Change password
          </Link>
          <div className="my-1 h-px bg-slate-100" />
          <div className="flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-[12.5px] text-slate-700">
            <span className="flex items-center gap-2.5">
              <span className="flex h-6 w-6 items-center justify-center rounded bg-slate-100 text-slate-600">
                <PaletteIcon />
              </span>
              Theme
            </span>
            <ThemeToggle size="sm" />
          </div>
          <div className="my-1 h-px bg-slate-100" />
          <button
            role="menuitem"
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[12.5px] text-slate-700 transition-colors hover:bg-slate-50"
            onClick={async () => {
              setOpen(false);
              await logout();
              router.replace("/login");
            }}
          >
            <span className="flex h-6 w-6 items-center justify-center rounded bg-slate-100 text-slate-600">
              <LogoutIcon />
            </span>
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function ShieldIcon() {
  return (
    <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l8 4v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4z" />
    </svg>
  );
}
function ChatIcon() {
  return (
    <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M21 12a8 8 0 11-16 0 8 8 0 0116 0z" />
    </svg>
  );
}
function LogoutIcon() {
  return (
    <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6-7H5a2 2 0 00-2 2v14a2 2 0 002 2h8" />
    </svg>
  );
}
function KeyIcon() {
  return (
    <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 7a4 4 0 100 8 4 4 0 000-8zm-4 4H3l3 3-3 3" />
    </svg>
  );
}
function PaletteIcon() {
  return (
    <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <circle cx="12" cy="12" r="9" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3a9 9 0 010 18" />
    </svg>
  );
}
