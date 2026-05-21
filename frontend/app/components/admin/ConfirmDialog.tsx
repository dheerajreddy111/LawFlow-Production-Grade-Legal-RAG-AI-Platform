"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle } from "lucide-react";
import { ReactNode, useEffect } from "react";
import { createPortal } from "react-dom";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "default" | "destructive";
  busy?: boolean;
  /** Confirm handler — return a promise to keep the spinner visible. */
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

/**
 * Minimal accessible confirmation modal. Portaled to <body> so it escapes
 * the admin layout's overflow:hidden constraint. Esc + backdrop close
 * call onCancel; Enter on the confirm button triggers it.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  busy,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onCancel();
    }
    document.addEventListener("keydown", onKey);
    // Prevent background scroll when modal is open.
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, busy, onCancel]);

  if (typeof document === "undefined") return null;
  const destructive = variant === "destructive";

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          aria-modal
          role="dialog"
          aria-labelledby="confirm-title"
        >
          {/* Backdrop */}
          <button
            type="button"
            aria-label="Close"
            disabled={busy}
            onClick={() => !busy && onCancel()}
            className="absolute inset-0 bg-[#0A1628]/35 backdrop-blur-[1px] disabled:cursor-not-allowed"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.97, y: 6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 4 }}
            transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            className="relative w-full max-w-md rounded-lg border border-slate-200/80 bg-white p-5 shadow-[0_18px_50px_-22px_rgba(10,22,40,0.35)]"
          >
            <div className="flex items-start gap-3">
              {destructive && (
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-red-50 text-red-600">
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                </span>
              )}
              <div className="flex-1">
                <h2
                  id="confirm-title"
                  className="font-display text-[15px] font-semibold leading-tight tracking-tight text-[#0A1628]"
                >
                  {title}
                </h2>
                <div className="mt-1.5 text-[12.5px] leading-relaxed text-slate-600">
                  {description}
                </div>
              </div>
            </div>

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={onCancel}
                disabled={busy}
                className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-[12.5px] font-medium text-slate-700 transition-colors hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {cancelLabel}
              </button>
              <button
                type="button"
                onClick={() => onConfirm()}
                disabled={busy}
                className={
                  destructive
                    ? "inline-flex items-center gap-1.5 rounded-md bg-red-600 px-3 py-1.5 text-[12.5px] font-semibold text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
                    : "inline-flex items-center gap-1.5 rounded-md bg-[#0A1628] px-3 py-1.5 text-[12.5px] font-semibold text-white transition-colors hover:bg-[#16335c] disabled:cursor-not-allowed disabled:opacity-60"
                }
              >
                {busy && (
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
                )}
                {confirmLabel}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
