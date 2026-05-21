"use client";

import { ReactNode } from "react";

import { cn } from "../../lib/cn";

interface SectionCardProps {
  title: string;
  subtitle?: ReactNode;
  /** Right-aligned content (e.g., a filter / time-range selector). */
  actions?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}

export function SectionCard({
  title,
  subtitle,
  actions,
  className,
  bodyClassName,
  children,
}: SectionCardProps) {
  return (
    <section
      className={cn(
        "rounded-lg border border-slate-200/70 bg-white",
        className,
      )}
    >
      <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-3">
        <div>
          <h3 className="font-display text-[13.5px] font-semibold leading-tight tracking-tight text-[#0A1628]">
            {title}
          </h3>
          {subtitle && (
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-slate-500">
              {subtitle}
            </p>
          )}
        </div>
        {actions}
      </header>
      <div className={cn("px-5 py-4", bodyClassName)}>{children}</div>
    </section>
  );
}
