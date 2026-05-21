"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  AlertOctagon,
  CheckCircle2,
  ChevronDown,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { cn } from "../../lib/cn";
import type {
  EvaluationReportSummary,
  EvaluationRowResult,
  EvaluationRunDetail,
} from "../../lib/admin/api";

interface EvaluationRunDrawerProps {
  detail: EvaluationRunDetail | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

/**
 * Slide-in right drawer for a single evaluation run. Renders the run's
 * aggregate metrics + per-row breakdown. Reuses the same portaled
 * pattern as the chat ExplainabilityPanel so it overlays cleanly above
 * the admin layout.
 */
export function EvaluationRunDrawer({
  detail,
  loading,
  error,
  onClose,
}: EvaluationRunDrawerProps) {
  const open = detail !== null || loading || error !== null;

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
            aria-label="Close detail"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-[#0A1628]/40 backdrop-blur-[2px]"
          />
          <motion.aside
            role="dialog"
            aria-modal
            aria-labelledby="eval-drawer-title"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "tween", duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[520px] flex-col border-l border-slate-200 bg-white shadow-[-30px_0_60px_-30px_rgba(10,22,40,0.28)]"
          >
            <header className="border-b border-slate-200 px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#9E6A0E]">
                    Evaluation run
                  </p>
                  <h2
                    id="eval-drawer-title"
                    className="mt-1 truncate font-display text-[17px] font-semibold leading-tight tracking-tight text-[#0A1628]"
                  >
                    {detail?.name ?? (loading ? "Loading…" : "Run")}
                  </h2>
                  {detail && (
                    <p className="mt-1 truncate text-[11.5px] text-slate-500">
                      {detail.dataset_filename} ·{" "}
                      {new Date(detail.created_at).toLocaleString()}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close"
                  className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-[#0A1628]"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </div>
            </header>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              {error && (
                <div
                  role="alert"
                  className="rounded-lg border border-red-200 bg-red-50/80 px-3.5 py-2.5 text-[12.5px] text-red-700"
                >
                  {error}
                </div>
              )}
              {loading && !detail && (
                <div className="lf-shimmer h-32 rounded-lg bg-slate-100" />
              )}
              {detail && (
                <div className="space-y-4">
                  <MetricsGrid summary={detail.report.summary} />
                  <RowsList rows={detail.report.results} />
                </div>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>,
    document.body,
  );
}

function MetricsGrid({ summary }: { summary: EvaluationReportSummary }) {
  const metrics: Array<{
    label: string;
    value: number;
    min: number;
    max: number;
  }> = [
    {
      label: "F1",
      value: summary.f1_score.mean,
      min: summary.f1_score.min,
      max: summary.f1_score.max,
    },
    {
      label: "Cosine",
      value: summary.cosine_similarity.mean,
      min: summary.cosine_similarity.min,
      max: summary.cosine_similarity.max,
    },
    {
      label: "Keyword",
      value: summary.keyword_overlap.mean,
      min: summary.keyword_overlap.min,
      max: summary.keyword_overlap.max,
    },
    {
      label: "Retrieval",
      value: summary.retrieval_confidence.mean,
      min: summary.retrieval_confidence.min,
      max: summary.retrieval_confidence.max,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-2.5">
      {metrics.map((m) => (
        <MetricCard key={m.label} {...m} />
      ))}
      <div className="col-span-2 flex items-center gap-2 rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2 text-[11.5px] text-slate-600">
        <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] text-emerald-700 ring-1 ring-emerald-200">
          {summary.scored_rows} scored
        </span>
        {summary.failed_rows > 0 && (
          <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] text-red-700 ring-1 ring-red-200">
            {summary.failed_rows} failed
          </span>
        )}
        <span className="ml-auto">total {summary.total_rows}</span>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  min,
  max,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  const tone =
    pct >= 80
      ? "text-emerald-700 bg-emerald-50 ring-emerald-200"
      : pct >= 50
      ? "text-[#9E6A0E] bg-[#FBF1DC] ring-[#E8C97A]/70"
      : "text-rose-700 bg-rose-50 ring-rose-200";

  return (
    <div className="rounded-lg border border-slate-100 bg-white p-3">
      <div className="flex items-start justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          {label}
        </p>
        <span
          className={cn(
            "tabular-nums rounded px-1.5 py-0.5 text-[10.5px] font-bold ring-1",
            tone,
          )}
        >
          {pct}%
        </span>
      </div>
      <p className="mt-1.5 font-display text-[20px] font-semibold leading-none tracking-tight text-[#0A1628]">
        {value.toFixed(3)}
      </p>
      <p className="mt-1.5 text-[10.5px] text-slate-400">
        min {min.toFixed(3)} · max {max.toFixed(3)}
      </p>
    </div>
  );
}

function RowsList({ rows }: { rows: EvaluationRowResult[] }) {
  if (rows.length === 0) {
    return <p className="text-[12.5px] text-slate-400">No rows in this run.</p>;
  }
  return (
    <div>
      <p className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
        Per-question breakdown · {rows.length}
      </p>
      <ul className="space-y-1.5">
        {rows.map((row, i) => (
          <RowItem key={i} row={row} index={i + 1} />
        ))}
      </ul>
    </div>
  );
}

function RowItem({ row, index }: { row: EvaluationRowResult; index: number }) {
  const [open, setOpen] = useState(false);
  const failed = row.error !== null;
  const f1 = Math.round(row.f1_score * 100);

  return (
    <li className="overflow-hidden rounded-lg border border-slate-100 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-slate-50"
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-bold tabular-nums text-slate-500 ring-1 ring-slate-200">
          {index}
        </span>
        <span className="min-w-0 flex-1 truncate font-display text-[12.5px] font-semibold text-[#0A1628]">
          {row.question || "(empty question)"}
        </span>
        <span
          className={cn(
            "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] ring-1",
            failed
              ? "bg-red-50 text-red-700 ring-red-200"
              : f1 >= 80
              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
              : f1 >= 50
              ? "bg-[#FBF1DC] text-[#9E6A0E] ring-[#E8C97A]/70"
              : "bg-rose-50 text-rose-700 ring-rose-200",
          )}
        >
          {failed ? (
            <span className="inline-flex items-center gap-1">
              <AlertOctagon className="h-2.5 w-2.5" aria-hidden /> error
            </span>
          ) : (
            `F1 ${f1}%`
          )}
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="space-y-2 border-t border-slate-100 px-3 py-3 text-[12px]">
              {failed ? (
                <div className="rounded bg-red-50 px-2.5 py-2 text-red-700 ring-1 ring-red-200">
                  {row.error}
                </div>
              ) : (
                <>
                  <KVField label="Expected" value={row.expected_answer} />
                  <KVField
                    label="Generated"
                    value={row.generated_answer}
                    icon={<CheckCircle2 className="h-3 w-3 text-emerald-600" aria-hidden />}
                  />
                  <dl className="grid grid-cols-4 gap-2 rounded-lg bg-slate-50/60 px-2.5 py-2 ring-1 ring-slate-100">
                    <Stat label="F1" value={row.f1_score} />
                    <Stat label="Cos" value={row.cosine_similarity} />
                    <Stat label="Kw" value={row.keyword_overlap} />
                    <Stat label="Conf" value={row.retrieval_confidence} />
                  </dl>
                  {(row.intent || row.route) && (
                    <p className="text-[10.5px] text-slate-500">
                      {row.intent && (
                        <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
                          {row.intent}
                        </span>
                      )}
                      {row.route && (
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
                          {row.route}
                        </span>
                      )}
                    </p>
                  )}
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

function KVField({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) {
  return (
    <div>
      <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
        {icon}
        {label}
      </p>
      <p className="mt-0.5 whitespace-pre-wrap break-words text-[12px] text-slate-700">
        {value}
      </p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        {label}
      </p>
      <p className="mt-0.5 font-mono text-[11.5px] font-semibold text-[#0A1628]">
        {value.toFixed(3)}
      </p>
    </div>
  );
}
