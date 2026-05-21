"use client";

import { type LucideIcon } from "lucide-react";

import { cn } from "../../lib/cn";

interface ComingNextProps {
  eyebrow: string;
  title: string;
  blurb: string;
  /** Bullet list of capabilities shipping in this section. */
  capabilities: string[];
  icon: LucideIcon;
  /** Optional phase label, e.g. "Phase B". */
  phase?: string;
}

/**
 * Premium "Coming next" placeholder shared by the four un-shipped admin
 * sections. Conveys what's planned without looking like a generic empty
 * state — keeps the navigation experience credible.
 */
export function ComingNext({
  eyebrow,
  title,
  blurb,
  capabilities,
  icon: Icon,
  phase,
}: ComingNextProps) {
  return (
    <div className="mx-auto max-w-3xl px-5 py-12 sm:px-8 sm:py-16">
      <div
        className={cn(
          "relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-8 shadow-[0_10px_40px_-22px_rgba(10,22,40,0.18)] sm:p-10",
        )}
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(600px 220px at 100% 0%, rgba(201,137,42,0.08), transparent 60%)",
          }}
        />
        <div className="relative">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#0A1628] text-[#D8A849] ring-1 ring-[#C9892A]/40">
              <Icon className="h-4 w-4" aria-hidden />
            </span>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#9E6A0E]">
                {eyebrow}
              </p>
              <h1 className="font-display text-[26px] font-semibold leading-tight tracking-tight text-[#0A1628]">
                {title}
              </h1>
            </div>
            {phase && (
              <span className="ml-auto rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-600">
                {phase}
              </span>
            )}
          </div>

          <p className="mt-5 max-w-xl text-[13.5px] leading-relaxed text-slate-600">
            {blurb}
          </p>

          <ul className="mt-6 grid gap-2 sm:grid-cols-2">
            {capabilities.map((c) => (
              <li
                key={c}
                className="flex items-start gap-2 rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2 text-[12.5px] text-slate-700"
              >
                <span className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[#C9892A]" />
                <span>{c}</span>
              </li>
            ))}
          </ul>

          <p className="mt-6 text-[11px] text-slate-400">
            The backend gate for this surface already exists. The UI lands in
            the next slice.
          </p>
        </div>
      </div>
    </div>
  );
}
