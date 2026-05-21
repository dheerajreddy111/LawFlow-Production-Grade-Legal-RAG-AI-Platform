"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, XCircle } from "lucide-react";
import { createContext, ReactNode, useCallback, useContext, useState } from "react";
import { createPortal } from "react-dom";

type ToastKind = "success" | "error";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  notify: (kind: ToastKind, message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/**
 * Lightweight toast provider. Renders into <body> so the toasts escape
 * the admin layout's overflow:hidden viewport. Toasts auto-dismiss after
 * 3.2s; multiple toasts stack from the bottom-right.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const notify = useCallback((kind: ToastKind, message: string) => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, kind, message }]);
    setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, 3200);
  }, []);

  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      {typeof document !== "undefined" &&
        createPortal(
          <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-full max-w-sm flex-col gap-2">
            <AnimatePresence initial={false}>
              {items.map((t) => (
                <motion.div
                  key={t.id}
                  initial={{ opacity: 0, y: 10, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 4, scale: 0.98 }}
                  transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
                  className={
                    "pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-white px-3.5 py-3 shadow-[0_14px_36px_-18px_rgba(10,22,40,0.35)] " +
                    (t.kind === "success"
                      ? "border-emerald-200"
                      : "border-red-200")
                  }
                  role="status"
                >
                  {t.kind === "success" ? (
                    <CheckCircle2
                      className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600"
                      aria-hidden
                    />
                  ) : (
                    <XCircle
                      className="mt-0.5 h-4 w-4 shrink-0 text-red-600"
                      aria-hidden
                    />
                  )}
                  <p className="text-[12.5px] leading-snug text-[#0A1628]">
                    {t.message}
                  </p>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>,
          document.body,
        )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
