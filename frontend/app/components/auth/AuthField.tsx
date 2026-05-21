"use client";

import { forwardRef, InputHTMLAttributes } from "react";

interface AuthFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  error?: string | null;
}

/**
 * Labelled input with accessible error wiring (aria-invalid + aria-describedby).
 * Visual treatment matches the existing chat-card aesthetic — soft slate
 * border, gold focus ring, subtle inner shadow.
 */
export const AuthField = forwardRef<HTMLInputElement, AuthFieldProps>(
  function AuthField({ label, hint, error, id, className, ...props }, ref) {
    const inputId = id ?? props.name ?? label.toLowerCase().replace(/\s+/g, "-");
    const errorId = error ? `${inputId}-error` : undefined;
    const hintId = hint && !error ? `${inputId}-hint` : undefined;

    return (
      <div className="space-y-1.5">
        <label
          htmlFor={inputId}
          className="block text-[11.5px] font-semibold uppercase tracking-[0.14em] text-slate-600"
        >
          {label}
        </label>
        <input
          {...props}
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={errorId ?? hintId}
          className={[
            "w-full rounded-lg border bg-white px-3.5 py-2.5 text-[14px] text-[#0A1628] placeholder:text-slate-400",
            "shadow-[inset_0_1px_0_rgba(10,22,40,0.04)]",
            "transition-colors focus:outline-none",
            error
              ? "border-red-300 focus:border-red-400 focus:ring-2 focus:ring-red-100"
              : "border-slate-200 focus:border-[#C9892A]/60 focus:ring-2 focus:ring-[#C9892A]/15",
            className ?? "",
          ].join(" ")}
        />
        {error ? (
          <p id={errorId} className="text-[12px] text-red-600">
            {error}
          </p>
        ) : hint ? (
          <p id={hintId} className="text-[12px] text-slate-500">
            {hint}
          </p>
        ) : null}
      </div>
    );
  }
);
