"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowDownRight, ArrowRight, ArrowUpRight, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { cn } from "../../lib/cn";
import {
  getEvaluationRun,
  type EvaluationReportSummary,
  type EvaluationRowResult,
  type EvaluationRunDetail,
} from "../../lib/admin/api";

interface EvaluationCompareDrawerProps {
  open: boolean;
  runIds: [number, number] | null;
  onClose: () => void;
}

type MetricKey = "f1_score" | "cosine_similarity" | "keyword_overlap" | "retrieval_confidence";
const METRICS: { key: MetricKey; label: string }[] = [
  { key: "f1_score", label: "F1" },
  { key: "cosine_similarity", label: "Cosine" },
  { key: "keyword_overlap", label: "Keyword" },
  { key: "retrieval_confidence", label: "Retrieval" },
];

// Below this absolute delta, we treat the metric as "flat" — no
// regression / improvement arrow. Without a noise floor every benchmark
// would always show movement, which is misleading.
const FLAT_THRESHOLD = 0.005;

/**
 * Side-by-side comparison drawer for two persisted evaluation runs.
 *
 * Fetches both runs, computes:
 *   - Aggregate metric deltas (run B – run A).
 *   - Per-question diff (which questions improved, which regressed,
 *     which stayed flat or exist only in one run).
 *
 * Reuses the same portaled-drawer style as EvaluationRunDrawer so the
 * surface feels familiar to operators.
 */
export function EvaluationCompareDrawer({
  open,
  runIds,
  onClose,
}: EvaluationCompareDrawerProps) {
  const [runA, setRunA] = useState<EvaluationRunDetail | null>(null);
  const [runB, setRunB] = useState<EvaluationRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !runIds) return;
    let cancelled = false;
    // The lint rule's setState-in-effect warning is well-meant, but the
    // pattern here is the canonical "kick off an async fetch in response
    // to props" — the request itself IS the external system, and the
    // loading flag is what the UI uses to render its skeleton. Splitting
    // this into refs would only obscure the intent.
    /* eslint-disable react-hooks/set-state-in-effect */
    setLoading(true);
    setError(null);
    setRunA(null);
    setRunB(null);
    /* eslint-enable react-hooks/set-state-in-effect */
    (async () => {
      try {
        const [a, b] = await Promise.all([
          getEvaluationRun(runIds[0]),
          getEvaluationRun(runIds[1]),
        ]);
        if (!cancelled) {
          // We always render A as the older run (smaller id) so deltas
          // read as "newer minus older" — improvements are positive.
          if (a.id < b.id) {
            setRunA(a);
            setRunB(b);
          } else {
            setRunA(b);
            setRunB(a);
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load runs.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, runIds]);

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
            aria-label="Close compare"
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
            aria-labelledby="cmp-drawer-title"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "tween", duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[680px] flex-col border-l border-slate-200 bg-white shadow-[-30px_0_60px_-30px_rgba(10,22,40,0.28)]"
          >
            <header className="border-b border-slate-200 px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#9E6A0E]">
                    Side-by-side
                  </p>
                  <h2
                    id="cmp-drawer-title"
                    className="mt-1 truncate font-display text-[17px] font-semibold leading-tight tracking-tight text-[#0A1628]"
                  >
                    Compare evaluation runs
                  </h2>
                  {runA && runB && (
                    <p className="mt-1 truncate text-[11.5px] text-slate-500">
                      <span className="font-mono">#{runA.id}</span>{" "}
                      <span className="text-slate-400">{runA.name}</span>{" "}
                      <ArrowRight
                        className="inline h-3 w-3 text-slate-400"
                        aria-hidden
                      />{" "}
                      <span className="font-mono">#{runB.id}</span>{" "}
                      <span className="text-slate-400">{runB.name}</span>
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

              {loading && (
                <div className="space-y-2">
                  <div className="lf-shimmer h-24 rounded-lg bg-slate-100" />
                  <div className="lf-shimmer h-48 rounded-lg bg-slate-100" />
                </div>
              )}

              {runA && runB && (
                <div className="space-y-5">
                  <MetricDeltas
                    a={runA.report.summary}
                    b={runB.report.summary}
                  />
                  <QuestionDiff
                    a={runA.report.results}
                    b={runB.report.results}
                  />
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

// ── Aggregate deltas ──────────────────────────────────────────────────────

function MetricDeltas({
  a,
  b,
}: {
  a: EvaluationReportSummary;
  b: EvaluationReportSummary;
}) {
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {METRICS.map((m) => {
        const av = a[m.key].mean;
        const bv = b[m.key].mean;
        const delta = bv - av;
        const tone = pickTone(delta);
        return (
          <div
            key={m.key}
            className="rounded-lg border border-slate-100 bg-white p-3"
          >
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              {m.label}
            </p>
            <div className="mt-1.5 flex items-baseline gap-3">
              <span className="font-mono text-[18px] font-semibold text-[#0A1628]">
                {bv.toFixed(3)}
              </span>
              <span className="text-[11px] text-slate-400">
                was {av.toFixed(3)}
              </span>
              <span
                className={cn(
                  "ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] font-bold ring-1",
                  tone.cls,
                )}
              >
                <tone.Icon className="h-2.5 w-2.5" aria-hidden />
                {delta >= 0 ? "+" : ""}
                {delta.toFixed(3)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function pickTone(delta: number): {
  cls: string;
  Icon: typeof ArrowUpRight;
} {
  if (Math.abs(delta) < FLAT_THRESHOLD) {
    return {
      cls: "bg-slate-100 text-slate-600 ring-slate-200",
      Icon: ArrowRight,
    };
  }
  if (delta > 0) {
    return {
      cls: "bg-emerald-50 text-emerald-700 ring-emerald-200",
      Icon: ArrowUpRight,
    };
  }
  return {
    cls: "bg-rose-50 text-rose-700 ring-rose-200",
    Icon: ArrowDownRight,
  };
}

// ── Per-question diff ─────────────────────────────────────────────────────

interface DiffRow {
  question: string;
  a: EvaluationRowResult | null;
  b: EvaluationRowResult | null;
  delta: number | null; // F1 delta (b - a); null when only one side has the row
}

function QuestionDiff({
  a,
  b,
}: {
  a: EvaluationRowResult[];
  b: EvaluationRowResult[];
}) {
  const [filter, setFilter] = useState<"all" | "regressed" | "improved" | "missing">(
    "all",
  );

  const rows = useMemo<DiffRow[]>(() => {
    const indexA = new Map(a.map((r) => [r.question.trim(), r]));
    const indexB = new Map(b.map((r) => [r.question.trim(), r]));
    const all = new Set<string>([...indexA.keys(), ...indexB.keys()]);
    return Array.from(all).map((q) => {
      const rowA = indexA.get(q) ?? null;
      const rowB = indexB.get(q) ?? null;
      const delta =
        rowA && rowB ? rowB.f1_score - rowA.f1_score : null;
      return { question: q, a: rowA, b: rowB, delta };
    });
  }, [a, b]);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (filter === "all") return true;
      if (filter === "missing") return r.a === null || r.b === null;
      if (r.delta === null) return false;
      if (filter === "regressed") return r.delta < -FLAT_THRESHOLD;
      if (filter === "improved") return r.delta > FLAT_THRESHOLD;
      return true;
    });
  }, [rows, filter]);

  const counts = useMemo(() => {
    let improved = 0;
    let regressed = 0;
    let flat = 0;
    let missing = 0;
    for (const r of rows) {
      if (r.a === null || r.b === null) {
        missing += 1;
      } else if (r.delta === null || Math.abs(r.delta) < FLAT_THRESHOLD) {
        flat += 1;
      } else if (r.delta > 0) {
        improved += 1;
      } else {
        regressed += 1;
      }
    }
    return { improved, regressed, flat, missing };
  }, [rows]);

  return (
    <div className="rounded-lg border border-slate-100 bg-white p-3">
      <header className="flex flex-wrap items-center gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Per-question diff
        </p>
        <span className="ml-auto flex items-center gap-1.5 text-[10.5px]">
          <ChipFilter active={filter === "all"} onClick={() => setFilter("all")} tone="slate">
            All · {rows.length}
          </ChipFilter>
          <ChipFilter
            active={filter === "improved"}
            onClick={() => setFilter("improved")}
            tone="emerald"
          >
            ↑ {counts.improved}
          </ChipFilter>
          <ChipFilter
            active={filter === "regressed"}
            onClick={() => setFilter("regressed")}
            tone="rose"
          >
            ↓ {counts.regressed}
          </ChipFilter>
          <ChipFilter
            active={filter === "missing"}
            onClick={() => setFilter("missing")}
            tone="amber"
          >
            ⤫ {counts.missing}
          </ChipFilter>
        </span>
      </header>

      <ul className="mt-2 space-y-1.5">
        {filtered.length === 0 ? (
          <li className="rounded-lg bg-slate-50/60 px-3 py-3 text-[12px] text-slate-500 ring-1 ring-slate-100">
            No rows match this filter.
          </li>
        ) : (
          filtered.map((r, i) => <DiffRowCard key={i} row={r} />)
        )}
      </ul>
    </div>
  );
}

function ChipFilter({
  active,
  onClick,
  tone,
  children,
}: {
  active: boolean;
  onClick: () => void;
  tone: "slate" | "emerald" | "rose" | "amber";
  children: React.ReactNode;
}) {
  const tones = {
    slate: active
      ? "bg-[#0A1628] text-[#D8A849]"
      : "bg-slate-50 text-slate-600 hover:bg-slate-100",
    emerald: active
      ? "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200"
      : "bg-emerald-50/60 text-emerald-700 hover:bg-emerald-100/80",
    rose: active
      ? "bg-rose-100 text-rose-800 ring-1 ring-rose-200"
      : "bg-rose-50/60 text-rose-700 hover:bg-rose-100/80",
    amber: active
      ? "bg-amber-100 text-amber-800 ring-1 ring-amber-200"
      : "bg-amber-50/60 text-amber-700 hover:bg-amber-100/80",
  } as const;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full px-2 py-0.5 font-semibold transition-colors",
        tones[tone],
      )}
    >
      {children}
    </button>
  );
}

function DiffRowCard({ row }: { row: DiffRow }) {
  const [open, setOpen] = useState(false);
  const onlyA = row.a !== null && row.b === null;
  const onlyB = row.b !== null && row.a === null;
  const both = row.a !== null && row.b !== null;

  const tone =
    onlyA || onlyB
      ? "bg-amber-50 text-amber-800 ring-amber-200"
      : row.delta !== null && row.delta > FLAT_THRESHOLD
      ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
      : row.delta !== null && row.delta < -FLAT_THRESHOLD
      ? "bg-rose-50 text-rose-800 ring-rose-200"
      : "bg-slate-100 text-slate-700 ring-slate-200";

  return (
    <li className="overflow-hidden rounded-lg border border-slate-100 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors hover:bg-slate-50"
      >
        <span
          className={cn(
            "mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] ring-1",
            tone,
          )}
        >
          {onlyA
            ? "missing in B"
            : onlyB
            ? "missing in A"
            : row.delta !== null && Math.abs(row.delta) < FLAT_THRESHOLD
            ? "flat"
            : row.delta !== null && row.delta > 0
            ? `+${row.delta.toFixed(2)}`
            : row.delta !== null
            ? row.delta.toFixed(2)
            : "—"}
        </span>
        <span className="min-w-0 flex-1 truncate font-display text-[12.5px] font-semibold text-[#0A1628]">
          {row.question || "(empty question)"}
        </span>
      </button>
      {open && both && (
        <div className="border-t border-slate-100 px-3 py-3 text-[12px]">
          <div className="grid grid-cols-2 gap-3">
            <SideCard label="Run A" row={row.a!} />
            <SideCard label="Run B" row={row.b!} />
          </div>
        </div>
      )}
      {open && onlyA && (
        <div className="border-t border-slate-100 px-3 py-3 text-[12px]">
          <SideCard label="Run A — absent from B" row={row.a!} />
        </div>
      )}
      {open && onlyB && (
        <div className="border-t border-slate-100 px-3 py-3 text-[12px]">
          <SideCard label="Run B — absent from A" row={row.b!} />
        </div>
      )}
    </li>
  );
}

function SideCard({
  label,
  row,
}: {
  label: string;
  row: EvaluationRowResult;
}) {
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50/40 p-2.5">
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#9E6A0E]">
        {label}
      </p>
      <div className="mt-1.5 grid grid-cols-4 gap-1.5">
        {METRICS.map((m) => (
          <div key={m.key}>
            <p className="text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              {m.label}
            </p>
            <p className="mt-0.5 font-mono text-[11.5px] font-semibold text-[#0A1628]">
              {row[m.key].toFixed(3)}
            </p>
          </div>
        ))}
      </div>
      {row.error ? (
        <p className="mt-2 break-words text-[11px] text-rose-700">{row.error}</p>
      ) : (
        <p className="mt-2 whitespace-pre-wrap break-words text-[11px] leading-relaxed text-slate-600">
          {row.generated_answer || "(no answer)"}
        </p>
      )}
    </div>
  );
}
