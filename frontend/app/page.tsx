"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import ChatMessage from "./components/ChatMessage";
import ChatInput from "./components/ChatInput";
import { ExplainabilityPanel } from "./components/ExplainabilityPanel";
import RightRail from "./components/RightRail";
import { UserMenu } from "./components/UserMenu";
import { useAuth } from "./lib/auth/context";
import { Message } from "./types";
import { streamQuery, sectionsToCitations } from "./lib/api";

// Monotonic, collision-proof message IDs. Date.now() collided when the
// user-message updater ran in the same millisecond that the assistant id
// was computed, causing patch() to mutate both bubbles.
// Globally-unique message IDs. crypto.randomUUID() can't collide across
// re-renders, Strict-Mode double-invokes, or dev Fast-Refresh module
// reloads (a monotonic counter resets to 0 on reload while React state
// persists → duplicate keys). Falls back for non-secure/old environments.
const newMessageId = (): string => {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

export default function Home() {
  const router = useRouter();
  const { status, session } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  /** id of the assistant message whose explainability panel is open, or null. */
  const [explainingMessageId, setExplainingMessageId] = useState<string | null>(null);
  const handleExplain = useCallback((messageId: string) => {
    setExplainingMessageId(messageId);
  }, []);
  const closeExplain = useCallback(() => setExplainingMessageId(null), []);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // Synchronous in-flight latch. `isLoading` is React state captured in the
  // render closure — two rapid sends (double Enter, or a suggestion/right-
  // rail chip firing handleSend before re-render) can both read it stale and
  // both proceed. A ref mutates synchronously and is immune to batching.
  const sendingRef = useRef(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Authoritative client-side gate. proxy.ts only handles /admin + /login +
  // /signup — the chat route is open so anonymous visitors see this page
  // and get redirected to /login. Skipped while the initial /auth/refresh
  // is still in flight so we don't bounce the user mid-bootstrap.
  useEffect(() => {
    if (status === "anonymous") {
      router.replace("/login");
    }
  }, [status, router]);

  const handleSend = async (text: string) => {
    const query = text.trim();
    if (!query || sendingRef.current) return;
    sendingRef.current = true;

    // Allocate both IDs up-front and synchronously so they are stable and
    // can never collide (the user id is no longer recomputed inside the
    // React updater).
    const userId = newMessageId();
    const assistantId = newMessageId();

    setMessages((prev) => [
      ...prev,
      {
        id: userId,
        role: "user",
        content: query,
        timestamp: new Date(),
      },
    ]);
    setInputValue("");
    setIsLoading(true);

    let created = false;

    // Append the assistant bubble lazily on the first event so the empty
    // card never flashes before any content/metadata arrives.
    const ensureMessage = () => {
      if (created) return;
      created = true;
      // Idempotent append: never add a second bubble for assistantId even
      // if this races with another stream event or a Strict-Mode re-invoke.
      setMessages((prev) =>
        prev.some((m) => m.id === assistantId)
          ? prev
          : [
              ...prev,
              {
                id: assistantId,
                role: "assistant",
                content: "",
                timestamp: new Date(),
                streaming: true,
              },
            ]
      );
    };

    const patch = (fn: (m: Message) => Message) =>
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? fn(m) : m))
      );

    try {
      await streamQuery(query, {
      onMeta: (meta) => {
        ensureMessage();
        patch((m) => ({
          ...m,
          citations: sectionsToCitations(meta.statute_sections),
          analysis: {
            intent: meta.intent,
            route: meta.route,
            confidence: meta.confidence,
            reason: meta.reason,
            entities: meta.entities,
            domain: meta.domain,
            relatedActs: meta.related_acts,
            suggestions: meta.suggestions,
            retrievedChunks: meta.retrieved_chunks ?? [],
          },
        }));
      },
      onToken: (text) => {
        ensureMessage();
        patch((m) => ({ ...m, content: m.content + text }));
      },
      onDone: () => {
        patch((m) => ({ ...m, streaming: false }));
        setIsLoading(false);
      },
      onError: (errMsg) => {
        if (created) {
          patch((m) => ({
            ...m,
            streaming: false,
            isError: true,
            content: errMsg,
          }));
        } else {
          setMessages((prev) => [
            ...prev,
            {
              id: assistantId,
              role: "assistant",
              isError: true,
              content: errMsg,
              timestamp: new Date(),
            },
          ]);
        }
        setIsLoading(false);
      },
      });
    } finally {
      // Always release the latch — even if streamQuery throws — so the
      // next send is never permanently blocked.
      sendingRef.current = false;
    }
  };

  // Brief, branded loading state during auth bootstrap. Without this we'd
  // render the chat UI for an instant before the redirect-on-anonymous
  // effect fires, which flashes a half-mounted experience.
  if (status === "loading" || (status === "anonymous" && !session)) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#ECEEF3]">
        <div className="flex items-center gap-2 text-[12px] text-slate-500">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#C9892A]" />
          <span>Restoring your LawFlow session…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[#ECEEF3]">
      {/* Main column */}
      <div className="flex flex-col flex-1 min-w-0">

        {/* ── Top navigation ── */}
        <header className="relative flex items-center gap-4 px-5 h-14 bg-[#0A1628] shrink-0">
          {/* gold hairline */}
          <div className="absolute inset-x-0 bottom-0 h-px bg-[#C9892A]/30" />

          {/* Brand */}
          <div className="flex items-center gap-2.5">
            <div className="flex w-7 h-7 items-center justify-center rounded-lg bg-[#C9892A]/15 ring-1 ring-[#C9892A]/30 shrink-0">
              <ScalesHeaderIcon />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-display text-[16px] font-semibold text-white tracking-tight">
                LawFlow
              </span>
              <span className="text-[9px] font-semibold text-[#D8A849]/85 tracking-[0.18em]">
                INDIA
              </span>
            </div>
          </div>

          <div className="flex-1" />

          {/* Right actions */}
          <UserMenu />
        </header>

        {/* ── Messages ── */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 space-y-8">

            {/* Empty-state hero */}
            {messages.length === 0 && !isLoading && (
              <div className="lf-rise flex flex-col items-center justify-center py-20 text-center">
                <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-xl bg-[#0A1628] ring-1 ring-[#C9892A]/30">
                  <span className="scale-[1.4]">
                    <ScalesHeaderIcon />
                  </span>
                </div>

                {/* Wordmark */}
                <div className="flex items-baseline gap-2">
                  <h1 className="font-display text-[34px] font-semibold leading-none tracking-tight text-[#0A1628]">
                    LawFlow
                  </h1>
                  <span className="text-[10px] font-semibold tracking-[0.2em] text-[#9E6A0E]">
                    INDIA
                  </span>
                </div>

                {/* Supporting copy */}
                <p className="mt-3 max-w-md text-[13px] leading-relaxed text-slate-500">
                  Hybrid legal AI for Indian law. Exact statutes resolved
                  deterministically; everything else answered by reranked
                  semantic retrieval — every response traced to the law it
                  stands on.
                </p>

                <div className="mt-8 grid w-full max-w-2xl gap-2.5 sm:grid-cols-3">
                  {[
                    {
                      tag: "Statute",
                      tone: "emerald",
                      q: "What does Section 302 of the Indian Penal Code say?",
                    },
                    {
                      tag: "Article",
                      tone: "navy",
                      q: "Explain Article 21 of the Constitution of India",
                    },
                    {
                      tag: "Research",
                      tone: "gold",
                      q: "Can police arrest without a warrant?",
                    },
                  ].map((ex) => (
                    <button
                      key={ex.q}
                      onClick={() => handleSend(ex.q)}
                      className="lf-lift group text-left rounded-xl border border-slate-200 bg-white px-4 py-3.5 hover:border-[#C9892A]/45 hover:shadow-[0_6px_20px_rgba(10,22,40,0.08)]"
                    >
                      <span
                        className={`inline-block text-[9px] font-bold uppercase tracking-[0.12em] px-1.5 py-0.5 rounded mb-2 ${
                          ex.tone === "emerald"
                            ? "bg-emerald-50 text-emerald-700"
                            : ex.tone === "gold"
                            ? "bg-[#FBF1DC] text-[#9E6A0E]"
                            : "bg-[#0A1628]/8 text-[#0A1628]"
                        }`}
                      >
                        {ex.tag}
                      </span>
                      <p className="text-[12.5px] text-slate-600 group-hover:text-[#0A1628] leading-snug transition-colors">
                        {ex.q}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Date separator */}
            {messages.length > 0 && (
              <div className="flex items-center gap-4">
                <div className="flex-1 h-px bg-gradient-to-r from-transparent to-slate-300/70" />
                <span className="font-display text-[11px] font-semibold text-slate-400 uppercase tracking-[0.2em]">
                  Today
                </span>
                <div className="flex-1 h-px bg-gradient-to-l from-transparent to-slate-300/70" />
              </div>
            )}

            {messages.map((message) => (
              <div key={message.id} className="lf-rise">
                <ChatMessage
                  message={message}
                  onSuggest={handleSend}
                  onExplain={handleExplain}
                />
              </div>
            ))}

            {/* Typing indicator — only until the streaming bubble appears */}
            {isLoading && !messages.some((m) => m.streaming) && (
              <div className="lf-rise flex items-start gap-3">
                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#0F2744] to-[#0A1628] ring-1 ring-[#C9892A]/25 flex items-center justify-center shrink-0 mt-1 shadow-sm">
                  <ScalesHeaderIcon />
                </div>
                <div className="lf-shimmer bg-white rounded-2xl rounded-tl-sm border border-slate-200/80 shadow-[0_2px_10px_rgba(10,22,40,0.06)] px-5 py-4">
                  <div className="flex items-center gap-3">
                    <div className="flex gap-1">
                      <span className="w-1.5 h-1.5 bg-[#C9892A] rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                      <span className="w-1.5 h-1.5 bg-[#C9892A] rounded-full animate-bounce" style={{ animationDelay: "160ms" }} />
                      <span className="w-1.5 h-1.5 bg-[#C9892A] rounded-full animate-bounce" style={{ animationDelay: "320ms" }} />
                    </div>
                    <span className="text-[12px] text-slate-500 font-medium">
                      Routing through legal orchestration…
                    </span>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* ── Input ── */}
        <ChatInput
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSend}
          isLoading={isLoading}
        />
      </div>

      {/* Right rail — context-aware from the latest analysed turn */}
      {(() => {
        const latest = [...messages]
          .reverse()
          .find((m) => m.analysis)?.analysis;
        return (
          <RightRail
            onSelectPrompt={handleSend}
            activeRoute={latest?.route}
            domain={latest?.domain ?? null}
            relatedActs={latest?.relatedActs ?? []}
            suggestions={latest?.suggestions ?? []}
            busy={isLoading}
          />
        );
      })()}

      {/* Explainability drawer — portaled, overlays the right rail */}
      <ExplainabilityPanel
        message={
          explainingMessageId
            ? messages.find((m) => m.id === explainingMessageId) ?? null
            : null
        }
        onClose={closeExplain}
      />
    </div>
  );
}

function ScalesHeaderIcon() {
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
