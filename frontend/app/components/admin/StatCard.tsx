"use client";

import { motion, useMotionValue, useTransform, animate } from "framer-motion";
import { type LucideIcon } from "lucide-react";
import { ReactNode, useEffect } from "react";

import { cn } from "../../lib/cn";

interface StatCardProps {
  label: string;
  value: number | string | null;
  /** Optional unit suffix (e.g. "ms", "%"). Ignored when value is a string. */
  unit?: string;
  /** Maximum decimal places when value is numeric. Default 0. */
  decimals?: number;
  icon?: LucideIcon;
  hint?: ReactNode;
  /** Visual tone — accent picks gold treatment for the most-prominent KPI. */
  tone?: "default" | "accent";
  loading?: boolean;
  className?: string;
}

/**
 * Animated KPI card.
 *
 * For numeric values, the count animates from 0 → target on mount using
 * framer-motion's motion value transform. String values render statically.
 * Loading state shows a shimmer skeleton — no layout shift on resolve.
 */
export function StatCard({
  label,
  value,
  unit,
  decimals = 0,
  icon: Icon,
  hint,
  tone = "default",
  loading,
  className,
}: StatCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "relative overflow-hidden rounded-lg border p-4",
        tone === "accent"
          ? "border-[#C9892A]/30 bg-[#FBF1DC]/30"
          : "border-slate-200/70 bg-white",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p
            className={cn(
              "text-[10.5px] font-semibold uppercase tracking-[0.14em]",
              tone === "accent" ? "text-[#9E6A0E]" : "text-slate-500",
            )}
          >
            {label}
          </p>
          <div className="mt-1.5 flex items-baseline gap-1.5">
            {loading ? (
              <span className="lf-shimmer block h-7 w-20 rounded bg-slate-100" />
            ) : typeof value === "number" ? (
              <AnimatedNumber value={value} decimals={decimals} />
            ) : (
              <span className="font-display text-[26px] font-semibold leading-none tracking-tight text-[#0A1628]">
                {value ?? "—"}
              </span>
            )}
            {unit && !loading && (
              <span className="text-[12px] font-medium text-slate-500">{unit}</span>
            )}
          </div>
        </div>
        {Icon && (
          <span
            className={cn(
              "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
              tone === "accent"
                ? "bg-[#C9892A]/15 text-[#9E6A0E]"
                : "bg-slate-50 text-slate-400 ring-1 ring-slate-200/70",
            )}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
          </span>
        )}
      </div>

      {hint && (
        <div className="mt-3 border-t border-slate-100 pt-2.5 text-[11px] text-slate-500">
          {hint}
        </div>
      )}
    </motion.div>
  );
}

function AnimatedNumber({ value, decimals }: { value: number; decimals: number }) {
  const mv = useMotionValue(0);
  const rounded = useTransform(mv, (latest) =>
    latest.toLocaleString(undefined, {
      maximumFractionDigits: decimals,
      minimumFractionDigits: decimals,
    }),
  );

  useEffect(() => {
    const controls = animate(mv, value, {
      duration: 0.9,
      ease: [0.16, 1, 0.3, 1],
    });
    return () => controls.stop();
  }, [mv, value]);

  return (
    <motion.span className="font-display text-[26px] font-semibold leading-none tracking-tight text-[#0A1628]">
      {rounded}
    </motion.span>
  );
}
