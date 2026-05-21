"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  ClipboardCheck,
  FileText,
  HeartPulse,
  KeyRound,
  LayoutDashboard,
  ListChecks,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect } from "react";
import { createPortal } from "react-dom";

import { cn } from "../../lib/cn";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/** Mirrors AdminSidebar's NAV, plus per-user surfaces that don't render
 *  in the desktop sidebar (Jobs, Settings — these appear in the user menu
 *  on desktop but get their own drawer entries on mobile). */
const NAV: NavItem[] = [
  { href: "/admin/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/admin/documents", label: "Documents", icon: FileText },
  { href: "/admin/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/admin/evaluation", label: "Evaluation", icon: ClipboardCheck },
  { href: "/admin/jobs", label: "Jobs", icon: ListChecks },
  { href: "/admin/system", label: "System Health", icon: HeartPulse },
  { href: "/admin/settings/password", label: "Account", icon: KeyRound },
];

interface AdminMobileDrawerProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Slide-in admin navigation for screens below the `lg` breakpoint.
 *
 * Mirrors the desktop AdminSidebar so the operator's mental model stays
 * the same. Closes on:
 *  - the backdrop click
 *  - Escape key
 *  - pathname change (route-aware close — see effect below)
 */
export function AdminMobileDrawer({ open, onClose }: AdminMobileDrawerProps) {
  const pathname = usePathname();

  // Route-aware close: any nav click changes the pathname, which dismisses
  // the drawer. Initial mount also runs but the drawer starts closed.
  useEffect(() => {
    if (open) onClose();
    // We intentionally depend on pathname *only* — open changes shouldn't
    // re-close the drawer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  // Esc to close + body-scroll lock while open.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.button
            type="button"
            aria-label="Close admin navigation"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-[#0A1628]/40 backdrop-blur-[2px] lg:hidden"
          />
          <motion.aside
            role="dialog"
            aria-label="Admin navigation"
            aria-modal
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ type: "tween", duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-slate-200 bg-white shadow-[30px_0_60px_-30px_rgba(10,22,40,0.32)] lg:hidden"
          >
            <header className="flex h-12 shrink-0 items-center gap-2 border-b border-slate-200/70 px-4">
              <Link
                href="/admin/overview"
                className="flex items-center gap-2"
                onClick={onClose}
              >
                <span className="flex h-6 w-6 items-center justify-center rounded-md bg-[#0A1628] ring-1 ring-[#C9892A]/35">
                  <ScalesIcon />
                </span>
                <span className="font-display text-[14px] font-semibold tracking-tight text-[#0A1628]">
                  LawFlow
                </span>
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-semibold tracking-[0.16em] text-slate-600">
                  ADMIN
                </span>
              </Link>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="ml-auto rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-50 hover:text-[#0A1628]"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </header>

            <nav className="flex-1 space-y-px px-2 py-3" aria-label="Admin navigation">
              <p className="px-3 pb-1 pt-2 text-[9.5px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Operations
              </p>
              {NAV.map((item) => {
                const active =
                  pathname === item.href ||
                  (item.href !== "/admin" && pathname?.startsWith(item.href));
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "group relative flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] transition-colors",
                      active
                        ? "bg-slate-50 text-[#0A1628]"
                        : "text-slate-600 hover:bg-slate-50/70 hover:text-[#0A1628]",
                    )}
                  >
                    {active && (
                      <span
                        aria-hidden
                        className="absolute inset-y-1.5 left-0 w-[2px] rounded-full bg-[#C9892A]"
                      />
                    )}
                    <Icon
                      className={cn(
                        "h-4 w-4 shrink-0",
                        active ? "text-[#9E6A0E]" : "text-slate-400 group-hover:text-slate-600",
                      )}
                      aria-hidden
                    />
                    <span className={cn("flex-1", active && "font-medium")}>
                      {item.label}
                    </span>
                  </Link>
                );
              })}
            </nav>

            <p className="mx-4 mb-4 mt-2 text-[10.5px] leading-relaxed text-slate-400">
              Admin actions are logged.
            </p>
          </motion.aside>
        </>
      )}
    </AnimatePresence>,
    document.body,
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
