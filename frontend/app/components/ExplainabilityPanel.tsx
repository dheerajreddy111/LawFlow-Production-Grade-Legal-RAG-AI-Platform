"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  BookText,
  Brain,
  ChevronDown,
  Code2,
  Compass,
  Layers,
  Lightbulb,
  ListTree,
  ScanLine,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import type {
  Citation,
  Message,
  RetrievedChunkRecord,
} from "../types";

interface ExplainabilityPanelProps {
  /** The message being explained — null when the panel is closed. */
  message: Message | null;
  onClose: () => void;
}

/**
 * "Why this answer?" right-side drawer.
 *
 * Surfaces every signal the SSE meta event emits — intent, route,
 * confidence, entities, statute provenance — in a single auditable
 * view. Sections are collapsible so casual users see a clean summary;
 * advanced mode reveals raw JSON for compliance / debugging.
 *
 * Render strategy: portaled to <body> so the drawer escapes the chat's
 * overflow:hidden viewport and sits above the right rail. The visible
 * width is capped at ~440px on desktop; on small screens it covers the
 * full viewport with a backdrop.
 */
export function ExplainabilityPanel({
  message,
  onClose,
}: ExplainabilityPanelProps) {
  // Body-scroll lock + esc-to-close while open.
  useEffect(() => {
    if (!message) return;
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
  }, [message, onClose]);

  if (typeof document === "undefined") return null;
  const open = message !== null;
  const analysis = message?.analysis;

  return createPortal(
    <AnimatePresence>
      {open && message && (
        <>
          {/* Backdrop — soft on desktop (right rail still visible-ish), opaque on mobile. */}
          <motion.button
            type="button"
            aria-label="Close explainability panel"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-[#0A1628]/40 backdrop-blur-[2px] sm:bg-[#0A1628]/15"
          />
          {/* Drawer */}
          <motion.aside
            role="dialog"
            aria-labelledby="explain-title"
            aria-modal
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "tween", duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[440px] flex-col border-l border-slate-200 bg-white shadow-[-30px_0_60px_-30px_rgba(10,22,40,0.28)]"
          >
            <PanelHeader
              route={analysis?.route ?? "unknown"}
              query={message.content.slice(0, 0) /* placeholder, real query comes from user message — see below */}
              onClose={onClose}
            />

            {/* Scrollable body */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              <SummaryCard analysis={analysis} />

              {analysis && (
                <Section icon={Compass} title="Routing decision" defaultOpen>
                  <RoutingDecision analysis={analysis} />
                </Section>
              )}

              {analysis && analysis.entities.length > 0 && (
                <Section icon={ScanLine} title={`Detected entities · ${analysis.entities.length}`}>
                  <EntitiesList entities={analysis.entities} />
                </Section>
              )}

              {message.citations && message.citations.length > 0 && (
                <Section
                  icon={BookText}
                  title={`Sources cited · ${message.citations.length}`}
                  defaultOpen
                >
                  <SourcesList citations={message.citations} />
                </Section>
              )}

              {analysis &&
                analysis.retrievedChunks &&
                analysis.retrievedChunks.length > 0 && (
                  <Section
                    icon={Layers}
                    title={`Retrieval scores · ${analysis.retrievedChunks.length}`}
                    defaultOpen
                  >
                    <RetrievedChunksList chunks={analysis.retrievedChunks} />
                  </Section>
                )}

              {analysis &&
                (analysis.domain ||
                  (analysis.relatedActs && analysis.relatedActs.length > 0) ||
                  (analysis.suggestions && analysis.suggestions.length > 0)) && (
                  <Section icon={Sparkles} title="Domain context">
                    <DomainContext analysis={analysis} />
                  </Section>
                )}

              <Section icon={Code2} title="Advanced — raw payload">
                <RawPayload message={message} />
              </Section>

              <p className="mt-6 text-[11px] leading-relaxed text-slate-400">
                LawFlow surfaces every routing + retrieval signal it
                acted on so the answer above is auditable. Outputs are
                research, not legal advice.
              </p>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>,
    document.body,
  );
}

// ── Header ────────────────────────────────────────────────────────────────

const ROUTE_BADGE: Record<
  string,
  { label: string; tone: string; dot: string; helper: string }
> = {
  deterministic: {
    label: "Statute-grounded",
    tone: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    dot: "bg-emerald-500",
    helper: "Exact statutory provision matched in the curated corpus.",
  },
  rag: {
    label: "AI Research (RAG)",
    tone: "bg-[#FBF1DC] text-[#9E6A0E] ring-[#E8C97A]/70",
    dot: "bg-[#C9892A]",
    helper: "Reranked semantic retrieval over the ingested corpus.",
  },
  conversation: {
    label: "Conversational",
    tone: "bg-slate-100 text-slate-700 ring-slate-200",
    dot: "bg-slate-500",
    helper: "Plain chat reply — no statute lookup or retrieval.",
  },
  unknown: {
    label: "Unrouted",
    tone: "bg-slate-100 text-slate-600 ring-slate-200",
    dot: "bg-slate-400",
    helper: "Query did not match any route — try one of the suggestions.",
  },
};

function PanelHeader({
  route,
  onClose,
}: {
  route: string;
  query: string;
  onClose: () => void;
}) {
  const badge = ROUTE_BADGE[route] ?? ROUTE_BADGE.unknown;
  return (
    <header className="border-b border-slate-200/70 px-5 py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#9E6A0E]">
            Explain this answer
          </p>
          <h2
            id="explain-title"
            className="mt-1 font-display text-[16px] font-semibold leading-tight tracking-tight text-[#0A1628]"
          >
            Why LawFlow answered this way
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="-mr-1 rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-50 hover:text-[#0A1628]"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${badge.tone}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${badge.dot}`} aria-hidden />
          {badge.label}
        </span>
      </div>
      <p className="mt-2 text-[11.5px] leading-relaxed text-slate-500">
        {badge.helper}
      </p>
    </header>
  );
}

// ── Sections ──────────────────────────────────────────────────────────────

function Section({
  icon: Icon,
  title,
  defaultOpen,
  children,
}: {
  icon: typeof Compass;
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen ?? false);
  return (
    <section className="mt-3 overflow-hidden rounded-lg border border-slate-200/70 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left transition-colors hover:bg-slate-50"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
          <Icon className="h-3.5 w-3.5" aria-hidden />
        </span>
        <span className="flex-1 font-display text-[12.5px] font-semibold tracking-tight text-[#0A1628]">
          {title}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="border-t border-slate-100 px-4 py-3.5">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

// ── Summary card (always visible) ─────────────────────────────────────────

function SummaryCard({ analysis }: { analysis: Message["analysis"] }) {
  if (!analysis) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4 text-[12.5px] text-slate-500">
        No analysis metadata is attached to this turn.
      </div>
    );
  }
  const confidence = Math.round(analysis.confidence * 100);
  const confidenceTone =
    confidence >= 80
      ? "text-emerald-700 bg-emerald-50 ring-emerald-200"
      : confidence >= 50
      ? "text-[#9E6A0E] bg-[#FBF1DC] ring-[#E8C97A]/70"
      : "text-rose-700 bg-rose-50 ring-rose-200";
  return (
    <div className="rounded-lg border border-slate-200/70 bg-white p-4">
      <div className="flex items-start gap-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#0A1628] text-[#D8A849]">
          <Lightbulb className="h-3.5 w-3.5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#9E6A0E]">
            Why this answer
          </p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-[#0A1628]">
            {analysis.reason || "Routed by the deterministic + RAG orchestration."}
          </p>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-slate-100 pt-3 text-[11.5px]">
        <span className="text-slate-500">Retrieval confidence</span>
        <span className="flex items-center gap-2">
          <span className="relative h-1.5 w-24 overflow-hidden rounded-full bg-slate-200">
            <motion.span
              initial={{ width: 0 }}
              animate={{ width: `${confidence}%` }}
              transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
              className={`absolute inset-y-0 left-0 rounded-full ${
                confidence >= 80
                  ? "bg-emerald-500"
                  : confidence >= 50
                  ? "bg-[#C9892A]"
                  : "bg-rose-500"
              }`}
            />
          </span>
          <span
            className={`tabular-nums rounded px-1.5 py-0.5 text-[10.5px] font-bold ring-1 ${confidenceTone}`}
          >
            {confidence}%
          </span>
        </span>
      </div>
    </div>
  );
}

// ── Routing decision ──────────────────────────────────────────────────────

function RoutingDecision({ analysis }: { analysis: NonNullable<Message["analysis"]> }) {
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-2.5 text-[12px]">
      <KVTile label="Intent" value={analysis.intent} mono />
      <KVTile label="Route" value={analysis.route} mono />
      <KVTile label="Confidence" value={`${Math.round(analysis.confidence * 100)}%`} mono />
      <KVTile label="Legal domain" value={analysis.domain || "—"} />
      <div className="col-span-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Routing rationale
        </p>
        <p className="mt-1 text-[12px] leading-relaxed text-slate-700">
          {analysis.reason || "Routed deterministically based on detected entities."}
        </p>
      </div>
    </dl>
  );
}

function KVTile({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50/60 px-2.5 py-1.5">
      <p className="text-[9.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
        {label}
      </p>
      <p
        className={`mt-0.5 text-[12px] font-semibold text-[#0A1628] ${mono ? "font-mono" : ""}`}
      >
        {value}
      </p>
    </div>
  );
}

// ── Entities ──────────────────────────────────────────────────────────────

const ENTITY_TONES: Record<string, string> = {
  SECTION: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  ACT: "bg-[#FBF1DC] text-[#9E6A0E] ring-[#E8C97A]/70",
  ARTICLE: "bg-blue-50 text-blue-700 ring-blue-200",
  COURT: "bg-purple-50 text-purple-700 ring-purple-200",
  YEAR: "bg-slate-100 text-slate-700 ring-slate-200",
};

function EntitiesList({
  entities,
}: {
  entities: NonNullable<Message["analysis"]>["entities"];
}) {
  return (
    <ul className="space-y-1.5">
      {entities.map((e, i) => {
        const tone = ENTITY_TONES[e.type] ?? "bg-slate-100 text-slate-700 ring-slate-200";
        const pct = Math.round(e.confidence * 100);
        return (
          <li
            key={i}
            className="flex items-center gap-2 rounded-lg border border-slate-100 bg-slate-50/40 px-2.5 py-1.5"
          >
            <span
              className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] ring-1 ${tone}`}
            >
              {e.type}
            </span>
            <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-[#0A1628]">
              {e.value}
            </span>
            <span className="shrink-0 text-[10.5px] font-bold tabular-nums text-slate-500">
              {pct}%
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// ── Sources ───────────────────────────────────────────────────────────────

function SourcesList({ citations }: { citations: Citation[] }) {
  return (
    <ol className="space-y-2">
      {citations.map((c, i) => (
        <li
          key={c.id}
          className="rounded-lg border border-slate-100 bg-slate-50/40 p-3"
        >
          <div className="flex items-start gap-2.5">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-[#0A1628] text-[10px] font-bold text-[#D8A849] tabular-nums">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-display text-[12.5px] font-semibold leading-tight text-[#0A1628]">
                {c.title}
              </p>
              <p className="mt-0.5 flex items-center gap-1.5 text-[10.5px] uppercase tracking-[0.12em] text-slate-500">
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9.5px] font-bold tracking-[0.08em] text-slate-600">
                  {c.type}
                </span>
                <span>{c.court}</span>
                {c.year && <span>· {c.year}</span>}
              </p>
              {c.excerpt && (
                <p className="mt-1.5 line-clamp-3 text-[12px] leading-relaxed text-slate-600">
                  {c.excerpt}
                </p>
              )}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

// ── Domain context ────────────────────────────────────────────────────────

function DomainContext({
  analysis,
}: {
  analysis: NonNullable<Message["analysis"]>;
}) {
  return (
    <div className="space-y-3 text-[12px]">
      {analysis.domain && (
        <div className="flex items-center gap-2">
          <Target className="h-3.5 w-3.5 text-slate-400" aria-hidden />
          <span className="text-slate-500">Domain</span>
          <span className="ml-auto rounded bg-[#0A1628]/8 px-1.5 py-0.5 text-[11px] font-semibold text-[#0A1628] ring-1 ring-[#0A1628]/12">
            {analysis.domain}
          </span>
        </div>
      )}
      {analysis.relatedActs && analysis.relatedActs.length > 0 && (
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            <ListTree className="h-3 w-3" aria-hidden />
            Related acts
          </p>
          <div className="flex flex-wrap gap-1.5">
            {analysis.relatedActs.map((a) => (
              <span
                key={a}
                className="rounded bg-slate-100 px-2 py-0.5 text-[11px] text-slate-700 ring-1 ring-slate-200"
              >
                {a}
              </span>
            ))}
          </div>
        </div>
      )}
      {analysis.suggestions && analysis.suggestions.length > 0 && (
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            <Brain className="h-3 w-3" aria-hidden />
            Suggested follow-ups
          </p>
          <ul className="space-y-1">
            {analysis.suggestions.slice(0, 4).map((s, i) => (
              <li
                key={i}
                className="flex items-start gap-1.5 text-[11.5px] leading-relaxed text-slate-600"
              >
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[#C9892A]" aria-hidden />
                <span>{s}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Retrieved chunks (RAG path) ───────────────────────────────────────────

/**
 * Per-chunk relevance display. For each retrieved-and-reranked chunk we show:
 *
 *   - The position (1, 2, 3 — top-down by rerank score)
 *   - The source string + section / act metadata if present
 *   - A compact bar that compares vector similarity vs reranker score, so
 *     the operator can spot reranker amplification (the dominant signal in
 *     the LawFlow stack — see backend rerank.py)
 *   - The terse human reason the reranker emitted for that chunk
 *
 * Render is deliberately compact — this is for operators tuning the
 * retrieval, not the casual reader.
 */
function RetrievedChunksList({ chunks }: { chunks: RetrievedChunkRecord[] }) {
  // Normalise scores to a 0–1 window for the bars. The reranker output is
  // already in [0, 1] but vector similarity can in theory go slightly
  // outside — clamp defensively so the visual scale stays honest.
  const maxRerank = Math.max(
    0.001,
    ...chunks.map((c) => c.rerank_score ?? 0),
  );

  return (
    <ol className="space-y-2">
      {chunks.map((c, i) => {
        const sim = clamp01(c.similarity);
        const rerank = clamp01((c.rerank_score ?? 0) / maxRerank);
        const tone =
          i === 0
            ? "text-emerald-700 ring-emerald-200 bg-emerald-50"
            : "text-[#9E6A0E] ring-[#E8C97A]/60 bg-[#FBF1DC]";
        const label = c.section ? `${c.section}${c.act ? ` · ${c.act}` : ""}` : c.source;
        return (
          <li
            key={i}
            className="rounded-lg border border-slate-100 bg-slate-50/40 px-3 py-2.5"
          >
            <div className="flex items-start gap-2.5">
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] ring-1 ${tone}`}
              >
                #{i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate font-display text-[12.5px] font-semibold text-[#0A1628]">
                  {label || c.source}
                </p>
                {label && label !== c.source && (
                  <p className="mt-0.5 truncate text-[10.5px] text-slate-500">
                    {c.source}
                  </p>
                )}
              </div>
            </div>

            <div className="mt-2 grid grid-cols-[60px_1fr_44px] items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500">
                Rerank
              </span>
              <span className="relative h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                <motion.span
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.round(rerank * 100)}%` }}
                  transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
                  className="absolute inset-y-0 left-0 rounded-full bg-[#C9892A]"
                />
              </span>
              <span className="text-right tabular-nums text-[10.5px] font-bold text-[#9E6A0E]">
                {((c.rerank_score ?? 0) as number).toFixed(2)}
              </span>

              <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500">
                Cosine
              </span>
              <span className="relative h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                <motion.span
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.round(sim * 100)}%` }}
                  transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
                  className="absolute inset-y-0 left-0 rounded-full bg-emerald-500"
                />
              </span>
              <span className="text-right tabular-nums text-[10.5px] font-bold text-emerald-700">
                {sim.toFixed(2)}
              </span>
            </div>

            {/* Hybrid-retrieval stage badges — appear when the hybrid
                pipeline surfaced them. The bi-encoder + BM25 are always
                set; the cross-encoder is opt-in. Older queries (or the
                LangGraph route) render only the existing bars above. */}
            {(c.bm25_rank != null ||
              c.fused_rank != null ||
              c.cross_encoder_score != null) && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px]">
                {c.fused_rank != null && (
                  <StageChip
                    label="Fused"
                    value={`#${c.fused_rank}`}
                    tone="navy"
                  />
                )}
                {c.vector_rank != null && (
                  <StageChip
                    label="Vector"
                    value={`#${c.vector_rank}`}
                    tone="emerald"
                  />
                )}
                {c.bm25_rank != null && (
                  <StageChip
                    label="BM25"
                    value={`#${c.bm25_rank}`}
                    tone="amber"
                  />
                )}
                {c.cross_encoder_score != null &&
                  c.cross_encoder_score !== 0 && (
                    <StageChip
                      label="CE"
                      value={c.cross_encoder_score.toFixed(2)}
                      tone="purple"
                    />
                  )}
              </div>
            )}

            {c.rerank_reason && (
              <p className="mt-2 line-clamp-2 break-words font-mono text-[10.5px] leading-relaxed text-slate-500">
                {c.rerank_reason}
              </p>
            )}
            {c.excerpt && (
              <p className="mt-1.5 line-clamp-3 text-[11.5px] leading-relaxed text-slate-600">
                {c.excerpt}
              </p>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function StageChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "navy" | "emerald" | "amber" | "purple";
}) {
  const tones = {
    navy: "bg-[#0A1628]/8 text-[#0A1628] ring-[#0A1628]/15",
    emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
    purple: "bg-purple-50 text-purple-700 ring-purple-200",
  } as const;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-semibold uppercase tracking-[0.08em] ring-1 ${tones[tone]}`}
    >
      <span className="opacity-70">{label}</span>
      <span className="tabular-nums">{value}</span>
    </span>
  );
}

function clamp01(v: number): number {
  if (Number.isNaN(v)) return 0;
  return Math.max(0, Math.min(1, v));
}

// ── Raw payload (advanced) ────────────────────────────────────────────────

function RawPayload({ message }: { message: Message }) {
  const payload = {
    role: message.role,
    streaming: message.streaming ?? false,
    isError: message.isError ?? false,
    analysis: message.analysis ?? null,
    citations: message.citations ?? [],
    contentPreview: message.content.slice(0, 240),
  };
  return (
    <pre className="max-h-72 overflow-auto rounded-lg bg-[#0A1628] p-3 font-mono text-[10.5px] leading-[1.55] text-[#D8E0EE]">
      {JSON.stringify(payload, null, 2)}
    </pre>
  );
}
