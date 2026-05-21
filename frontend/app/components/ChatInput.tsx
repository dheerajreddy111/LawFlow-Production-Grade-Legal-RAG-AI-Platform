"use client";

import { KeyboardEvent, useEffect, useRef } from "react";

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string) => void;
  isLoading: boolean;
}

export default function ChatInput({
  value,
  onChange,
  onSend,
  isLoading,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
  }, [value]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading && value.trim()) onSend(value);
    }
  };

  const canSend = value.trim().length > 0 && !isLoading;

  return (
    <div className="shrink-0 border-t border-slate-200/70 bg-white px-5 py-3.5">
      <div className="mx-auto max-w-3xl space-y-2">
        {/* Input container */}
        <div className="relative flex items-end gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 transition-colors focus-within:border-[#C9892A]/50 focus-within:ring-1 focus-within:ring-[#C9892A]/15">
          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about Indian law or describe your legal matter…"
            rows={1}
            className="flex-1 resize-none bg-transparent py-1 text-[14.5px] leading-relaxed text-[#0A1628] outline-none placeholder:text-slate-400"
            style={{ maxHeight: "160px" }}
          />

          {/* Send */}
          <button
            type="button"
            onClick={() => canSend && onSend(value)}
            disabled={!canSend}
            aria-label={isLoading ? "Sending" : "Send message"}
            className="mb-0.5 flex h-7 w-7 shrink-0 items-center justify-center self-end rounded-lg bg-[#0A1628] text-white transition-colors hover:bg-[#16335c] disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {isLoading ? (
              <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden>
                <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
                <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
              </svg>
            ) : (
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14m0 0l-6-6m6 6l-6 6" />
              </svg>
            )}
          </button>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-1 text-[10.5px] text-slate-400">
          <span>
            <kbd className="rounded border border-slate-200 bg-slate-50 px-1 py-px font-sans text-[10px]">
              Enter
            </kbd>{" "}
            to send ·{" "}
            <kbd className="rounded border border-slate-200 bg-slate-50 px-1 py-px font-sans text-[10px]">
              Shift Enter
            </kbd>{" "}
            new line
          </span>
          <span>Research only — not legal advice</span>
        </div>
      </div>
    </div>
  );
}
