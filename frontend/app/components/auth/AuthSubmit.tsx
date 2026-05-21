"use client";

import { ButtonHTMLAttributes, ReactNode } from "react";

interface AuthSubmitProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  pending?: boolean;
  variant?: "primary" | "admin";
  children: ReactNode;
}

export function AuthSubmit({
  pending,
  variant = "primary",
  disabled,
  children,
  className,
  ...props
}: AuthSubmitProps) {
  const base =
    "group relative inline-flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-[13.5px] font-semibold tracking-wide transition-all disabled:cursor-not-allowed";
  const tone =
    variant === "admin"
      ? "bg-gradient-to-r from-[#0F2744] via-[#0A1628] to-[#060D18] text-[#D8A849] ring-1 ring-[#C9892A]/40 hover:ring-[#C9892A]/60 hover:shadow-[0_8px_24px_-12px_rgba(10,22,40,0.55)]"
      : "bg-gradient-to-r from-[#0F2744] to-[#0A1628] text-white ring-1 ring-[#0A1628] hover:from-[#16335c] hover:to-[#0F2744] hover:shadow-[0_6px_18px_-10px_rgba(10,22,40,0.5)]";

  return (
    <button
      {...props}
      type={props.type ?? "submit"}
      disabled={disabled || pending}
      className={[base, tone, disabled || pending ? "opacity-70" : "", className ?? ""].join(" ")}
    >
      {pending ? (
        <span className="flex items-center gap-2">
          <Spinner />
          <span>Please wait…</span>
        </span>
      ) : (
        <>
          <span>{children}</span>
          <svg
            className="h-3.5 w-3.5 -mr-0.5 opacity-70 transition-transform group-hover:translate-x-0.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            aria-hidden
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M14 5l7 7m0 0l-7 7m7-7H3"
            />
          </svg>
        </>
      )}
    </button>
  );
}

function Spinner() {
  return (
    <svg
      className="h-3.5 w-3.5 animate-spin"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeOpacity="0.25"
        strokeWidth="3"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}
