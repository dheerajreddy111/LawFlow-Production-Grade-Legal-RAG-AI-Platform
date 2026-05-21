"use client";

import { useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

// Custom sanitiser schema — extends the default with our `data-lf-badge`
// attribute on <span>. Without this whitelist the sanitiser strips the
// attribute and the `[[badge]]` preprocessor renders as a plain word.
const SANITIZE_SCHEMA = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    span: [...(defaultSchema.attributes?.span ?? []), ["data-lf-badge"]],
  },
};

import { Citation, Message, MessageAnalysis } from "../types";
import CitationCard from "./CitationCard";

/** Primary provision shown by default; the rest collapse under a toggle. */
function ProvisionList({
  citations,
  deterministic,
}: {
  citations: Citation[];
  deterministic: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [primary, ...related] = citations;

  return (
    <div className="px-5 pb-4 border-t border-slate-100 pt-3 space-y-0">
      <p className="font-display text-[10px] font-semibold text-[#0A1628]/55 uppercase tracking-[0.16em] mb-1">
        Primary Provision
      </p>
      <CitationCard citation={primary} deterministic={deterministic} primary />

      {related.length > 0 && (
        <div className="mt-1">
          <button
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="flex items-center gap-2 w-full text-left py-1.5 group/related"
          >
            <svg
              className={`w-3.5 h-3.5 text-slate-400 transition-transform duration-200 ${
                open ? "rotate-90" : ""
              }`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2.5}
                d="M9 5l7 7-7 7"
              />
            </svg>
            <span className="font-display text-[10px] font-semibold text-[#0A1628]/45 uppercase tracking-[0.16em] group-hover/related:text-[#9E6A0E] transition-colors">
              Related Provisions
            </span>
            <span className="text-[10px] font-bold text-slate-400 bg-slate-100 rounded-full px-1.5 py-0.5">
              {related.length}
            </span>
            <span className="ml-auto text-[10px] text-slate-400 group-hover/related:text-[#9E6A0E] transition-colors">
              {open ? "Hide" : "Show"}
            </span>
          </button>
          {open && (
            <div className="lf-rise">
              {related.map((c) => (
                <CitationCard
                  key={c.id}
                  citation={c}
                  deterministic={deterministic}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── [[badge]] inline marker ────────────────────────────────────────────────
//
// Our model output uses `[[Section 25F]]` as an inline badge. That syntax is
// NOT standard markdown, so we preprocess it into a custom `<span>` with a
// data attribute that the react-markdown sanitiser allows through, then
// render it as a pill in `components.span`. Anywhere the LLM produces
// `[[X]]` the operator gets a chip; everywhere else the brackets render as
// plain text.
const BADGE_RE = /\[\[([^\]]+)\]\]/g;
function preprocessBadges(content: string): string {
  // Replace [[X]] with an HTML span the sanitiser will preserve.
  return content.replace(
    BADGE_RE,
    (_match, inner) =>
      `<span data-lf-badge="true">${escapeHtml(String(inner))}</span>`,
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// react-markdown component overrides — keep the typographic style of the
// hand-rolled parser, just with a real markdown library underneath. The
// components map drives the entire ReactMarkdown render; anything not
// overridden falls through to the library defaults.
const MD_COMPONENTS: Components = {
  p: ({ children }) => (
    <p className="text-[15px] leading-[1.72] text-slate-700">{children}</p>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-slate-900">{children}</strong>
  ),
  em: ({ children }) => <em className="italic text-slate-700">{children}</em>,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-[#9E6A0E] underline-offset-2 hover:underline"
    >
      {children}
    </a>
  ),
  ul: ({ children }) => (
    <ul className="my-3 list-disc space-y-1.5 pl-5 marker:text-[#C9892A]">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="my-3 list-decimal space-y-1.5 pl-5 marker:font-semibold marker:text-[#C9892A]">
      {children}
    </ol>
  ),
  li: ({ children }) => (
    <li className="pl-1 text-[15px] leading-[1.65] text-slate-700">
      {children}
    </li>
  ),
  h1: ({ children }) => (
    <h2 className="mt-6 mb-2 font-display text-[15px] font-semibold uppercase tracking-wider text-[#0A1628] first:mt-0">
      {children}
    </h2>
  ),
  h2: ({ children }) => (
    <h2 className="mt-6 mb-2 font-display text-[14px] font-semibold uppercase tracking-wider text-[#0A1628] first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-5 mb-1.5 font-display text-[13px] font-semibold uppercase tracking-wider text-[#0A1628]">
      {children}
    </h3>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-[#C9892A]/55 bg-slate-50/60 px-3.5 py-2 text-[14px] italic text-slate-600">
      {children}
    </blockquote>
  ),
  code: ({ children, className, ...props }) => {
    // react-markdown v9+ removed the `inline` prop; block code lives inside
    // <pre> and carries a `language-…` className from remark. Distinguish by
    // className presence — anything else is treated as inline.
    const isBlock = typeof className === "string" && /language-/.test(className);
    if (isBlock) {
      return (
        <code className={`font-mono text-[12.5px] ${className}`} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code
        className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12.5px] text-[#0A1628]"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="my-3 overflow-x-auto rounded-lg border border-slate-200 bg-[#0A1628] p-3 text-[12.5px] leading-relaxed text-[#D8E0EE]">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full text-[13px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="border-b border-slate-200 bg-slate-50">{children}</thead>
  ),
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => (
    <tr className="border-t border-slate-100 first:border-t-0 hover:bg-slate-50/60 transition-colors">
      {children}
    </tr>
  ),
  th: ({ children }) => (
    <th className="whitespace-nowrap px-4 py-2.5 text-left font-semibold text-slate-600">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-4 py-2.5 text-slate-600">{children}</td>
  ),
  hr: () => <hr className="my-4 border-t border-slate-200" />,
  // Custom badge handler — the preprocessor wraps [[X]] markers in a
  // sentinel span; we recognise it via data-lf-badge. The sanitiser strips
  // unknown attributes by default; see `rehypeSanitizeSchema` below for
  // why this attribute survives.
  span: ({ children, ...props }) => {
    const dataAttrs = props as Record<string, unknown>;
    if (dataAttrs["data-lf-badge"]) {
      return (
        <span className="relative top-[-1px] mx-0.5 inline-flex items-center rounded border border-[#0A1628]/15 bg-[#0A1628]/8 px-1.5 py-0.5 font-mono text-[11px] font-semibold leading-none text-[#0A1628]">
          {children}
        </span>
      );
    }
    return <span {...props}>{children}</span>;
  },
};

function MarkdownRenderer({ content }: { content: string }) {
  // Preprocessing is memoised so we don't rebuild on every keystroke during
  // streaming. The content reference is stable within one render.
  const prepared = useMemo(() => preprocessBadges(content), [content]);
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      // rehype-raw parses the inline HTML injected by `preprocessBadges` so
      // our sentinel <span> becomes a real node; rehype-sanitize then runs
      // *after* with our extended schema so the badge attribute survives.
      rehypePlugins={[rehypeRaw, [rehypeSanitize, SANITIZE_SCHEMA]]}
      components={MD_COMPONENTS}
      // The default mode adds `\n` between block siblings; skipHtml false
      // would refuse our preprocessed <span>. rehypeSanitize handles the
      // safety bit — react-markdown itself trusts the rehype output.
    >
      {prepared}
    </ReactMarkdown>
  );
}

const TAG_STYLES: Record<string, string> = {
  "Labour Law": "bg-blue-50 text-blue-700 border-blue-200",
  "IDA 1947": "bg-amber-50 text-amber-800 border-amber-200",
  "Compensation": "bg-emerald-50 text-emerald-700 border-emerald-200",
  "IDA §25F": "bg-amber-50 text-amber-800 border-amber-200",
  "Criminal Law": "bg-red-50 text-red-700 border-red-200",
  "Constitutional": "bg-purple-50 text-purple-700 border-purple-200",
};

function TagChip({ label }: { label: string }) {
  const style =
    TAG_STYLES[label] ?? "bg-slate-100 text-slate-600 border-slate-200";
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border ${style}`}
    >
      {label}
    </span>
  );
}

// Deterministic vs RAG route — visually distinct so the hybrid orchestration
// is legible at a glance.
const ROUTE_CONFIG: Record<
  string,
  { label: string; cls: string; dot: string; icon: string }
> = {
  deterministic: {
    label: "Statute-Grounded",
    cls: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    dot: "bg-emerald-500",
    icon: "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z",
  },
  rag: {
    label: "AI Research",
    cls: "bg-[#FBF1DC] text-[#9E6A0E] ring-[#E8C97A]/70",
    dot: "bg-[#C9892A]",
    icon: "M13 10V3L4 14h7v7l9-11h-7z",
  },
  unknown: {
    label: "Unrouted",
    cls: "bg-slate-100 text-slate-600 ring-slate-200",
    dot: "bg-slate-400",
    icon: "M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  },
};

function RouteBadge({ route }: { route: string }) {
  const c = ROUTE_CONFIG[route] ?? ROUTE_CONFIG.unknown;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${c.cls}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} aria-hidden />
      {c.label}
    </span>
  );
}

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  const tone =
    pct >= 80
      ? { bar: "bg-emerald-500", text: "text-emerald-700" }
      : pct >= 50
      ? { bar: "bg-[#C9892A]", text: "text-[#9E6A0E]" }
      : { bar: "bg-rose-500", text: "text-rose-600" };
  return (
    <span className="inline-flex items-center gap-1.5" title={`Confidence ${pct}%`}>
      <span className="text-[9px] font-semibold uppercase tracking-wider text-slate-400">
        Confidence
      </span>
      <span className="relative h-1.5 w-16 rounded-full bg-slate-200 overflow-hidden">
        <span
          className={`lf-meter-fill absolute inset-y-0 left-0 rounded-full ${tone.bar}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className={`text-[10px] font-bold tabular-nums ${tone.text}`}>
        {pct}%
      </span>
    </span>
  );
}

// Expandable AI-transparency panel: a compact summary row that opens to
// reveal full orchestration insight (why this route, domain, entities).
function AnalysisStrip({ analysis }: { analysis: MessageAnalysis }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-slate-100">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 px-5 py-2 text-left transition-colors hover:bg-slate-50/50"
      >
        <RouteBadge route={analysis.route} />
        {analysis.domain && (
          <span className="hidden rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600 sm:inline-flex">
            {analysis.domain}
          </span>
        )}
        <ConfidenceMeter value={analysis.confidence} />
        <span className="ml-auto flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
          {open ? "Hide" : "Why"}
          <svg
            className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
          </svg>
        </span>
      </button>

      {open && (
        <div className="lf-rise px-5 pb-3.5 pt-1 space-y-2.5 text-[12px]">
          <div className="grid grid-cols-2 gap-2">
            <Insight label="Intent" value={analysis.intent} mono />
            <Insight label="Route" value={analysis.route} mono />
            <Insight
              label="Legal domain"
              value={analysis.domain || "—"}
            />
            <Insight
              label="Retrieval confidence"
              value={`${Math.round(analysis.confidence * 100)}%`}
              mono
            />
          </div>
          <div>
            <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">
              Matched entities
            </p>
            {analysis.entities.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {analysis.entities.map((e, i) => (
                  <span
                    key={i}
                    title={`${e.type} · ${Math.round(e.confidence * 100)}%`}
                    className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium font-mono bg-white text-slate-500 ring-1 ring-slate-200"
                  >
                    {e.type}:{e.value}
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-[11px] text-slate-400">none</span>
            )}
          </div>
          <div>
            <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">
              Why this happened
            </p>
            <p className="text-[12px] leading-relaxed text-slate-600">
              {analysis.reason}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function Insight({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="bg-white rounded-lg ring-1 ring-slate-200 px-2.5 py-1.5">
      <p className="text-[10px] text-slate-400 uppercase tracking-wider">
        {label}
      </p>
      <p
        className={`text-[12px] text-[#0A1628] font-semibold ${
          mono ? "font-mono" : ""
        }`}
      >
        {value}
      </p>
    </div>
  );
}

const SUGGESTED_QUERIES = [
  "What is the punishment for cheating?",
  "Can police arrest without a warrant?",
  "Is a WhatsApp screenshot valid evidence?",
  "What does Section 302 of the IPC say?",
];

export default function ChatMessage({
  message,
  onSuggest,
  onExplain,
}: {
  message: Message;
  onSuggest?: (q: string) => void;
  /** Open the explainability panel for this message. Hidden when undefined. */
  onExplain?: (messageId: string) => void;
}) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end gap-2.5 items-end">
        <div className="max-w-[68%] bg-gradient-to-br from-[#0F2744] to-[#0A1628] text-white rounded-2xl rounded-br-sm px-5 py-3.5 shadow-[0_6px_18px_rgba(10,22,40,0.22)] ring-1 ring-white/5">
          <p className="text-[15px] leading-[1.66] font-light">{message.content}</p>
        </div>
        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[#C9892A]/30 to-[#C9892A]/10 ring-1 ring-[#C9892A]/40 flex items-center justify-center shrink-0 text-[#9E6A0E] text-[11px] font-bold">
          D
        </div>
      </div>
    );
  }

  if (message.isError) {
    return (
      <div className="flex gap-3 items-start">
        <div className="w-7 h-7 rounded-lg bg-rose-600 flex items-center justify-center shrink-0 mt-1 shadow-sm">
          <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 9v2m0 4h.01M5.07 19h13.86c1.54 0 2.5-1.67 1.73-3L13.73 4a2 2 0 00-3.46 0L3.34 16c-.77 1.33.19 3 1.73 3z" />
          </svg>
        </div>
        <div className="flex-1 min-w-0 bg-rose-50 rounded-2xl rounded-tl-sm border border-rose-200 px-5 py-4">
          <p className="text-[11px] font-bold text-rose-600 uppercase tracking-[0.14em] mb-1.5">
            Request Failed
          </p>
          <p className="text-[14px] leading-[1.6] text-rose-800">
            {message.content}
          </p>
        </div>
      </div>
    );
  }

  // Conversation / unknown — plain chat reply. No legal-analysis chrome:
  // no analysis strip, no confidence, no provisions, no citations.
  const route = message.analysis?.route;
  if (route === "conversation" || route === "unknown") {
    return (
      <div className="flex gap-3 items-start">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#0F2744] to-[#0A1628] ring-1 ring-[#C9892A]/25 flex items-center justify-center shrink-0 mt-1 shadow-sm">
          <ScalesIcon />
        </div>
        <div className="flex-1 min-w-0 bg-white rounded-2xl rounded-tl-sm ring-1 ring-slate-200/80 shadow-[0_2px_10px_rgba(10,22,40,0.06)] px-5 py-4">
          <div className="space-y-1.5">
            <MarkdownRenderer content={message.content} />
            {message.streaming && <span className="lf-cursor" aria-hidden />}
          </div>
          {route === "unknown" && !message.streaming && onSuggest && (
            <div className="mt-4 pt-3 border-t border-slate-100">
              <p className="font-display text-[10px] font-semibold text-[#0A1628]/45 uppercase tracking-[0.16em] mb-2">
                Try asking
              </p>
              <div className="flex flex-wrap gap-1.5">
                {SUGGESTED_QUERIES.map((q) => (
                  <button
                    key={q}
                    onClick={() => onSuggest(q)}
                    className="lf-lift text-[12px] text-slate-600 hover:text-[#0A1628] bg-slate-50 hover:bg-[#C9892A]/10 ring-1 ring-slate-200 hover:ring-[#C9892A]/40 rounded-full px-3 py-1.5 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 items-start group">
      {/* Avatar */}
      <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#0F2744] to-[#0A1628] ring-1 ring-[#C9892A]/25 flex items-center justify-center shrink-0 mt-1 shadow-sm">
        <ScalesIcon />
      </div>

      {/* Card */}
      <div className="min-w-0 flex-1 overflow-hidden rounded-xl rounded-tl-sm border border-slate-200/70 bg-white">
        {/* Card header — LEGAL ANALYSIS label + tags */}
        <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-2.5">
          <span className="text-slate-400">
            <AnalysisIcon />
          </span>
          <span className="font-display text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Legal Analysis
          </span>
          {message.tags && message.tags.length > 0 && (
            <>
              <span className="text-slate-300 text-xs">·</span>
              <div className="flex items-center gap-1.5 flex-wrap">
                {message.tags.map((tag) => (
                  <TagChip key={tag} label={tag} />
                ))}
              </div>
            </>
          )}
        </div>

        {/* Analysis metadata — intent · route · confidence · entities */}
        {message.analysis && <AnalysisStrip analysis={message.analysis} />}

        {/* Content — incremental while streaming */}
        <div className="px-5 py-5 space-y-1.5">
          {message.content ? (
            <>
              <MarkdownRenderer content={message.content} />
              {message.streaming && <span className="lf-cursor" aria-hidden />}
            </>
          ) : message.streaming ? (
            <p className="flex items-center gap-1 text-[14px] italic text-slate-400">
              Generating response
              <span className="lf-cursor" aria-hidden />
            </p>
          ) : null}
        </div>

        {/* Provisions — primary foregrounded, related collapsed */}
        {message.citations && message.citations.length > 0 && (
          <ProvisionList
            citations={message.citations}
            deterministic={message.analysis?.route === "deterministic"}
          />
        )}

        {/* Action bar — hover only */}
        <div className="px-5 py-2.5 border-t border-slate-100 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
          <ActionBtn
            label="Copy"
            icon="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
          />
          <ActionBtn
            label="Save to Matter"
            icon="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"
          />
          <ActionBtn
            label="Helpful"
            icon="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5"
            hoverColor="hover:text-emerald-600"
          />
          <ActionBtn
            label="Flag"
            icon="M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9"
            hoverColor="hover:text-rose-500"
          />
          {onExplain && message.analysis && (
            <button
              type="button"
              onClick={() => onExplain(message.id)}
              className="ml-auto flex items-center gap-1.5 rounded-md bg-[#0A1628]/5 px-2.5 py-1 text-[11px] font-semibold text-[#0A1628]/75 ring-1 ring-[#0A1628]/10 transition-all hover:bg-[#C9892A]/15 hover:text-[#9E6A0E] hover:ring-[#C9892A]/40"
              title="Why this answer? — open the explainability panel"
            >
              <svg
                className="h-3.5 w-3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth={1.75}
                viewBox="0 0 24 24"
                aria-hidden
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                />
              </svg>
              Explain
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ActionBtn({
  icon,
  label,
  hoverColor = "hover:text-slate-700",
}: {
  icon: string;
  label: string;
  hoverColor?: string;
}) {
  return (
    <button
      className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] text-slate-400 ${hoverColor} hover:bg-slate-50 transition-colors`}
    >
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d={icon} />
      </svg>
      {label}
    </button>
  );
}

function ScalesIcon() {
  return (
    <svg
      className="w-4 h-4 text-[#C9892A]"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.75}
        d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3"
      />
    </svg>
  );
}

function AnalysisIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.75}
        d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"
      />
    </svg>
  );
}
