"use client";

interface RightRailProps {
  onSelectPrompt: (prompt: string) => void;
  activeRoute?: string;
  domain?: string | null;
  relatedActs?: string[];
  suggestions?: string[];
  busy?: boolean;
}

/** Visualises the hybrid pipeline; highlights the branch the last query took. */
function OrchestrationPanel({
  activeRoute,
  busy,
}: {
  activeRoute?: string;
  busy?: boolean;
}) {
  const det = activeRoute === "deterministic";
  const rag = activeRoute === "rag";
  return (
    <section className="rounded-xl ring-1 ring-[#0A1628]/10 bg-gradient-to-br from-[#0A1628] to-[#0F2744] p-4 text-white overflow-hidden relative">
      <div className="absolute -right-6 -top-6 w-20 h-20 rounded-full bg-[#C9892A]/10 blur-xl" />
      <div className="flex items-center gap-2 mb-3">
        <span className="relative flex w-2 h-2">
          {busy && (
            <span className="lf-live-dot absolute inline-flex w-2 h-2 rounded-full bg-[#C9892A]" />
          )}
          <span className="relative inline-flex w-2 h-2 rounded-full bg-[#D8A849]" />
        </span>
        <span className="font-display text-[11px] font-semibold uppercase tracking-[0.16em] text-white/80">
          AI Orchestration
        </span>
      </div>

      <div className="space-y-1.5">
        <PipelineStep label="Intent classification" active state="done" />
        <PipelineStep
          label="Deterministic — statute corpus"
          active={det}
          state={det ? "hit" : rag ? "skip" : "idle"}
        />
        <PipelineStep
          label="RAG — retrieval + research"
          active={rag}
          state={rag ? "hit" : det ? "skip" : "idle"}
        />
        <PipelineStep label="Grounded answer" active state="done" />
      </div>

      <p className="mt-3 text-[10.5px] leading-relaxed text-white/45">
        Statute lookups resolve deterministically; everything else falls back
        to retrieval-augmented research.
      </p>
    </section>
  );
}

function PipelineStep({
  label,
  active,
  state,
}: {
  label: string;
  active?: boolean;
  state: "done" | "hit" | "skip" | "idle";
}) {
  const dot =
    state === "hit"
      ? "bg-[#D8A849]"
      : state === "done"
      ? "bg-emerald-400"
      : state === "skip"
      ? "bg-white/15"
      : "bg-white/25";
  return (
    <div
      className={`flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 transition-colors ${
        active ? "bg-white/[0.07] ring-1 ring-[#C9892A]/30" : ""
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
      <span
        className={`text-[11px] ${
          state === "skip"
            ? "text-white/30 line-through"
            : active
            ? "text-white font-medium"
            : "text-white/60"
        }`}
      >
        {label}
      </span>
    </div>
  );
}

const PRACTICE_AREAS = [
  { label: "Labour & Employment", icon: "M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z", active: true },
  { label: "Corporate & Commercial", icon: "M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4", active: false },
  { label: "Constitutional Law", icon: "M8 14v3m4-3v3m4-3v3M3 21h18M3 10h18M3 7l9-4 9 4M4 10h16v11H4V10z", active: false },
  { label: "Criminal Law", icon: "M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3", active: false },
  { label: "Intellectual Property", icon: "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z", active: false },
];

const QUICK_PROMPTS = [
  "What are the grounds for writ petition under Article 226?",
  "Explain Section 138, Negotiable Instruments Act 1881",
  "Draft a legal notice under Consumer Protection Act 2019",
  "What is the limitation period under Limitation Act 1963?",
  "Conditions for anticipatory bail under Section 438 CrPC",
];

const JURISDICTIONS = [
  { label: "Supreme Court of India", short: "SC", color: "bg-[#0A1628] text-white" },
  { label: "Delhi High Court", short: "DHC", color: "bg-slate-600 text-white" },
  { label: "Bombay High Court", short: "BHC", color: "bg-slate-600 text-white" },
  { label: "NCLAT", short: "NCLAT", color: "bg-slate-500 text-white" },
  { label: "NCLT", short: "NCLT", color: "bg-slate-500 text-white" },
];

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span className="font-display text-[10px] font-semibold text-[#0A1628]/45 uppercase tracking-[0.18em] whitespace-nowrap">
        {label}
      </span>
      <div className="flex-1 h-px bg-slate-200" />
    </div>
  );
}

export default function RightRail({
  onSelectPrompt,
  activeRoute,
  domain,
  relatedActs = [],
  suggestions = [],
  busy,
}: RightRailProps) {
  const hasContext = Boolean(domain) || relatedActs.length > 0;
  const prompts = suggestions.length > 0 ? suggestions : QUICK_PROMPTS;
  return (
    <aside className="hidden lg:flex flex-col w-[300px] shrink-0 bg-white border-l border-slate-200 overflow-y-auto">
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-100 bg-gradient-to-b from-[#0A1628]/[0.035] to-transparent">
        <p className="font-display text-[14px] font-semibold text-[#0A1628]">
          Legal Intelligence
        </p>
        <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">
          Indian statutory law · Case law · Tribunals
        </p>
      </div>

      <div className="p-5 space-y-7">
        {/* Hybrid orchestration */}
        <OrchestrationPanel activeRoute={activeRoute} busy={busy} />

        {/* Detected context — dynamic */}
        {hasContext && (
          <section className="rounded-xl ring-1 ring-[#C9892A]/25 bg-gradient-to-b from-[#FEFBF3] to-white p-4">
            <div className="flex items-center gap-2 mb-2.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[#C9892A] lf-live-dot" />
              <span className="font-display text-[10px] font-semibold text-[#7A5010] uppercase tracking-[0.16em]">
                Detected Context
              </span>
            </div>
            {domain && (
              <div className="mb-2.5">
                <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">
                  Legal domain
                </p>
                <span className="inline-flex items-center px-2.5 py-1 rounded-md text-[12px] font-semibold bg-[#0A1628]/8 text-[#0A1628] ring-1 ring-[#0A1628]/12">
                  {domain}
                </span>
              </div>
            )}
            {relatedActs.length > 0 && (
              <div>
                <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">
                  Relevant acts
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {relatedActs.map((a) => (
                    <span
                      key={a}
                      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-white text-slate-600 ring-1 ring-slate-200"
                    >
                      {a}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>
        )}

        {/* Practice Areas */}
        <section>
          <SectionHeader label="Practice Areas" />
          <div className="space-y-1">
            {PRACTICE_AREAS.map((area, i) => (
              <button
                key={i}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-[12px] transition-all text-left group ${
                  area.active
                    ? "bg-[#0A1628]/8 text-[#0A1628] font-semibold"
                    : "text-slate-500 hover:text-[#0A1628] hover:bg-slate-50"
                }`}
              >
                <svg
                  className={`w-3.5 h-3.5 shrink-0 transition-colors ${
                    area.active
                      ? "text-[#C9892A]"
                      : "text-slate-400 group-hover:text-[#C9892A]"
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.75}
                    d={area.icon}
                  />
                </svg>
                {area.label}
                {area.active && (
                  <span className="ml-auto w-1.5 h-1.5 rounded-full bg-[#C9892A]" />
                )}
              </button>
            ))}
          </div>
        </section>

        {/* Suggested questions — context-aware when available */}
        <section>
          <SectionHeader
            label={suggestions.length > 0 ? "Suggested Questions" : "Quick Prompts"}
          />
          <div className="space-y-1.5">
            {prompts.map((prompt, i) => (
              <button
                key={i}
                onClick={() => onSelectPrompt(prompt)}
                className="w-full text-left px-3 py-2.5 rounded-xl bg-slate-50 hover:bg-[#0A1628]/5 border border-transparent hover:border-[#0A1628]/12 text-[12px] text-slate-600 hover:text-[#0A1628] transition-all group"
              >
                <span className="flex items-start gap-2">
                  <svg
                    className="w-3 h-3 mt-0.5 shrink-0 text-slate-300 group-hover:text-[#C9892A] transition-colors"
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
                  {prompt}
                </span>
              </button>
            ))}
          </div>
        </section>

        {/* Jurisdictions */}
        <section>
          <SectionHeader label="Jurisdictions" />
          <div className="flex flex-wrap gap-1.5">
            {JURISDICTIONS.map((j, i) => (
              <span
                key={i}
                title={j.label}
                className={`inline-flex items-center px-2 py-1 rounded text-[10px] font-bold tracking-wide cursor-default ${j.color}`}
              >
                {j.short}
              </span>
            ))}
          </div>
          <p className="text-[11px] text-slate-400 mt-2 leading-relaxed">
            Covers all 25 High Courts, Supreme Court, and major Tribunals.
          </p>
        </section>

        {/* Disclaimer */}
        <section className="rounded-xl border border-[#E8C97A]/50 bg-[#FEFBF3] p-4">
          <div className="flex gap-2.5">
            <svg
              className="w-3.5 h-3.5 text-[#C9892A] shrink-0 mt-0.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.75}
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <div>
              <p className="text-[11px] font-semibold text-[#7A5010] mb-1">
                Professional Use Only
              </p>
              <p className="text-[11px] text-[#9E7030] leading-relaxed">
                This platform provides legal research assistance and does not
                constitute legal advice under the Advocates Act, 1961. Consult
                a qualified advocate for specific matters.
              </p>
            </div>
          </div>
        </section>

        {/* Project attribution */}
        <footer className="pt-4 border-t border-slate-100">
          <p className="text-[11px] text-slate-400 leading-relaxed">
            Developed by{" "}
            <a
              href="https://www.linkedin.com/in/dheerajreddythumma/"
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-slate-500 hover:text-[#9E6A0E] transition-colors"
            >
              @DheerajReddyThumma
            </a>
          </p>
          <div className="flex items-center justify-between mt-2">
            <a
              href="https://github.com/dheerajreddy111"
              target="_blank"
              rel="noopener noreferrer"
              className="group/gh inline-flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-[#9E6A0E] transition-colors"
            >
              <svg
                viewBox="0 0 24 24"
                aria-hidden
                className="w-3.5 h-3.5 fill-current transition-transform duration-200 group-hover/gh:-translate-y-0.5"
              >
                <path d="M12 .5C5.73.5.5 5.73.5 12a11.5 11.5 0 0 0 7.86 10.93c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.34-1.3-1.7-1.3-1.7-1.06-.72.08-.71.08-.71 1.17.08 1.79 1.2 1.79 1.2 1.04 1.79 2.73 1.27 3.4.97.1-.76.41-1.27.74-1.56-2.56-.29-5.25-1.28-5.25-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.43-2.69 5.4-5.26 5.69.42.36.8 1.08.8 2.18v3.23c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5Z" />
              </svg>
              <span className="font-medium tracking-wide">Source on GitHub</span>
            </a>
            <span className="inline-flex items-center gap-1.5 text-[10px] font-mono text-slate-300">
              <span className="w-1 h-1 rounded-full bg-[#C9892A]/60" />
              LawFlow v1.0
            </span>
          </div>
        </footer>
      </div>
    </aside>
  );
}
