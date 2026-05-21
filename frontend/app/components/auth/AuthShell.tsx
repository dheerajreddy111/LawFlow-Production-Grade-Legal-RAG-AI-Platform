"use client";

import Link from "next/link";
import { ReactNode } from "react";

/**
 * Shared layout chrome for /login, /signup, /admin/login.
 *
 * The variant prop swaps the accent treatment — admin gets a deeper navy
 * gradient + the "Admin Portal" badge so the page is visually distinct
 * from the user-facing flow without rebuilding the layout.
 */
export type AuthShellVariant = "user" | "admin";

interface AuthShellProps {
  variant?: AuthShellVariant;
  eyebrow?: string;
  title: string;
  subtitle?: ReactNode;
  /** Optional footer link below the card (e.g. "Need an account? Sign up"). */
  footer?: ReactNode;
  children: ReactNode;
}

export function AuthShell({
  variant = "user",
  eyebrow,
  title,
  subtitle,
  footer,
  children,
}: AuthShellProps) {
  const isAdmin = variant === "admin";
  return (
    <div
      className={`relative h-screen w-screen overflow-auto ${
        isAdmin ? "bg-[#0A1628]" : "bg-[#F7F8FB]"
      }`}
    >
      {/* Subtle ambient backdrop — one soft gradient, not three. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background: isAdmin
            ? "radial-gradient(900px 480px at 12% -10%, rgba(201,137,42,0.10), transparent 60%)"
            : "radial-gradient(720px 380px at 12% -10%, rgba(201,137,42,0.07), transparent 60%)",
        }}
      />

      <main className="relative mx-auto flex min-h-screen w-full max-w-[420px] flex-col items-center justify-center px-5 py-12">
        {/* Brand block — compact, single line */}
        <Link
          href="/"
          className="mb-8 flex items-center gap-2.5"
          aria-label="LawFlow home"
        >
          <span
            className={`flex h-8 w-8 items-center justify-center rounded-lg ring-1 ring-[#C9892A]/35 ${
              isAdmin ? "bg-[#0F2744]" : "bg-[#0A1628]"
            }`}
          >
            <ScalesIcon />
          </span>
          <span className="flex items-baseline gap-2">
            <span
              className={`font-display text-[20px] font-semibold leading-none tracking-tight ${
                isAdmin ? "text-white" : "text-[#0A1628]"
              }`}
            >
              LawFlow
            </span>
            <span
              className={`text-[9px] font-semibold tracking-[0.22em] ${
                isAdmin ? "text-[#D8A849]/85" : "text-[#9E6A0E]"
              }`}
            >
              INDIA
            </span>
          </span>
        </Link>

        {/* Card */}
        <section
          className="lf-rise w-full rounded-xl border border-slate-200/80 bg-white px-6 py-6 shadow-sm"
          aria-labelledby="auth-title"
        >
          {eyebrow && (
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-[#9E6A0E]">
              {eyebrow}
            </p>
          )}
          <h1
            id="auth-title"
            className="font-display text-[22px] font-semibold leading-tight tracking-tight text-[#0A1628]"
          >
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1.5 text-[13px] leading-relaxed text-slate-500">
              {subtitle}
            </p>
          )}
          <div className="mt-5">{children}</div>
        </section>

        {footer && (
          <div
            className={`mt-5 text-center text-[12.5px] ${
              isAdmin ? "text-slate-300/85" : "text-slate-500"
            }`}
          >
            {footer}
          </div>
        )}

        <div
          className={`mt-10 text-center text-[11px] leading-relaxed tracking-wide ${
            isAdmin ? "text-slate-400/70" : "text-slate-400"
          }`}
        >
          <div>Built by Dheeraj Reddy Thumma</div>
          <div>
            GitHub:{" "}
            <a
              href="https://github.com/dheerajreddy111"
              target="_blank"
              rel="noreferrer noopener"
              className="underline-offset-4 hover:underline"
            >
              @dheerajreddy111
            </a>
          </div>
        </div>
      </main>
    </div>
  );
}

function ScalesIcon() {
  return (
    <svg
      className="h-6 w-6 text-[#C9892A]"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.6}
        d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3"
      />
    </svg>
  );
}
