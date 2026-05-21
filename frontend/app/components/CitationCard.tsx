"use client";

import { Citation } from "../types";

const COURT_CONFIG: Record<string, { label: string; bg: string; text: string }> = {
  "Supreme Court of India": {
    label: "SC",
    bg: "bg-[#0A1628]",
    text: "text-white",
  },
  "Delhi High Court": { label: "DHC", bg: "bg-slate-600", text: "text-white" },
  "Bombay High Court": {
    label: "BHC",
    bg: "bg-slate-600",
    text: "text-white",
  },
  "Calcutta High Court": {
    label: "CHC",
    bg: "bg-slate-600",
    text: "text-white",
  },
  "Madras High Court": {
    label: "MHC",
    bg: "bg-slate-600",
    text: "text-white",
  },
  "Central Act": { label: "CENTRAL ACT", bg: "bg-[#8B5E10]", text: "text-white" },
};

const TYPE_LABEL: Record<Citation["type"], string> = {
  case: "Case Law",
  statute: "Statutory Reference",
  provision: "Legal Provision",
  article: "Constitutional Article",
};

function CaseIcon() {
  return (
    <svg
      className="w-3.5 h-3.5"
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

function BookIcon() {
  return (
    <svg
      className="w-3.5 h-3.5"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.75}
        d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
      />
    </svg>
  );
}

export default function CitationCard({
  citation,
  deterministic = false,
  primary = false,
}: {
  citation: Citation;
  deterministic?: boolean;
  primary?: boolean;
}) {
  const court =
    COURT_CONFIG[citation.court] ?? {
      label: citation.court.slice(0, 4).toUpperCase(),
      bg: "bg-slate-600",
      text: "text-white",
    };

  const isCase = citation.type === "case";
  // Deterministic route returns the single exact match — label it as the
  // primary provision rather than a generic "Legal Provision".
  const isProvision =
    citation.type === "provision" || citation.type === "statute";
  const typeLabel =
    (primary || deterministic) && isProvision
      ? "Primary Provision"
      : TYPE_LABEL[citation.type];

  return (
    <div className="lf-lift group/cite rounded-xl ring-1 ring-[#E8C97A]/55 overflow-hidden bg-gradient-to-b from-[#FEFCF5] to-[#FBF4E2] my-3 shadow-[0_1px_4px_rgba(158,106,14,0.08)] hover:ring-[#D4A843]/70 hover:shadow-[0_8px_22px_rgba(158,106,14,0.13)]">
      {/* Card header */}
      <div className="flex items-center gap-2.5 px-4 py-2.5 bg-[#FCEFD2]/70 border-b border-[#E8C97A]/40">
        <span className="flex items-center justify-center w-5 h-5 rounded-md bg-[#C9892A]/12 text-[#9E6A0E]">
          {isCase ? <CaseIcon /> : <BookIcon />}
        </span>
        <span className="font-display text-[10px] font-semibold text-[#7A5010] uppercase tracking-[0.14em]">
          {typeLabel}
        </span>
        <div className="flex-1" />
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold tracking-wide ${court.bg} ${court.text}`}
        >
          {court.label}
        </span>
      </div>

      {/* Card body */}
      <div className="px-4 py-3.5">
        <p className="text-[14px] font-semibold text-slate-800 leading-snug">
          {citation.title}
        </p>
        <p className="text-[12px] text-[#9E6A0E] font-mono mt-1 tracking-wide">
          {citation.citation}
        </p>
        {citation.excerpt && (
          <blockquote className="mt-3 pl-3.5 border-l-2 border-[#D4A843] text-[13px] text-slate-600 italic leading-relaxed">
            &ldquo;{citation.excerpt}&rdquo;
          </blockquote>
        )}
      </div>

      {/* Card footer */}
      <div className="px-4 py-2 border-t border-[#E8C97A]/30 flex items-center gap-4">
        <button className="text-[11px] font-semibold text-[#9E6A0E] hover:text-[#7A5010] transition-colors">
          Copy Citation
        </button>
        <button className="text-[11px] text-slate-400 hover:text-slate-600 transition-colors">
          View Full Text
        </button>
        {citation.year && (
          <span className="ml-auto text-[11px] text-slate-400 font-mono">
            {citation.year}
          </span>
        )}
      </div>
    </div>
  );
}
