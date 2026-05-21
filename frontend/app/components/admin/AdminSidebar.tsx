"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  ClipboardCheck,
  FileText,
  HeartPulse,
  LayoutDashboard,
  ListChecks,
  type LucideIcon,
} from "lucide-react";

import { cn } from "../../lib/cn";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** When true, render a small "soon" pill — section is wired but unstubbed. */
  soon?: boolean;
}

const NAV: NavItem[] = [
  { href: "/admin/overview",   label: "Overview",       icon: LayoutDashboard },
  { href: "/admin/documents",  label: "Documents",      icon: FileText },
  { href: "/admin/analytics",  label: "Analytics",      icon: BarChart3 },
  { href: "/admin/evaluation", label: "Evaluation",     icon: ClipboardCheck },
  { href: "/admin/jobs",       label: "Jobs",           icon: ListChecks },
  { href: "/admin/system",     label: "System Health",  icon: HeartPulse },
];

export function AdminSidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-56 shrink-0 border-r border-slate-200/70 bg-white lg:flex lg:flex-col">
      <div className="px-4 pb-3 pt-5">
        <p className="text-[9.5px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          Admin
        </p>
        <p className="mt-1 font-display text-[14.5px] font-semibold leading-tight tracking-tight text-[#0A1628]">
          Operations
        </p>
      </div>

      <nav className="flex-1 space-y-px px-2" aria-label="Admin navigation">
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
                "group relative flex items-center gap-2.5 rounded-md px-3 py-1.5 text-[12.5px] transition-colors",
                active
                  ? "bg-slate-50 text-[#0A1628]"
                  : "text-slate-600 hover:bg-slate-50/70 hover:text-[#0A1628]",
              )}
            >
              {/* Linear-style 2px left accent on the active item. */}
              {active && (
                <span
                  aria-hidden
                  className="absolute inset-y-1.5 left-0 w-[2px] rounded-full bg-[#C9892A]"
                />
              )}
              <Icon
                className={cn(
                  "h-3.5 w-3.5 shrink-0",
                  active
                    ? "text-[#9E6A0E]"
                    : "text-slate-400 group-hover:text-slate-600",
                )}
                aria-hidden
              />
              <span className={cn("flex-1", active && "font-medium")}>
                {item.label}
              </span>
              {item.soon && (
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                  Soon
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <p className="mx-4 mb-4 mt-2 text-[10.5px] leading-relaxed text-slate-400">
        Admin actions are logged.
      </p>
    </aside>
  );
}
