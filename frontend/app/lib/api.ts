import {
  Citation,
  StatuteSection,
  StreamCallbacks,
  StreamMeta,
} from "../types";
import { apiStreamFetch } from "./auth/client";

/** Stable per-tab session id so the backend can keep multi-turn memory. */
function getSessionId(): string {
  if (typeof window === "undefined") return "server";
  try {
    let sid = sessionStorage.getItem("lawflow_session_id");
    if (!sid) {
      sid =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      sessionStorage.setItem("lawflow_session_id", sid);
    }
    return sid;
  } catch {
    return "anon";
  }
}

// The non-streaming POST /api/v1/query client was removed during cleanup —
// the UI uses streamQuery() (SSE) exclusively. The endpoint still exists
// server-side for the evaluation pipeline / API consumers.

/** Parse one raw SSE frame ("event: x\ndata: {...}") into {event, data}. */
function parseSSEFrame(
  raw: string
): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

/**
 * Stream a legal query via SSE (POST /api/v1/query/stream).
 * Invokes callbacks as `meta` / `token` / `done` / `error` frames arrive.
 * Network and protocol faults are reported through `onError`, never thrown.
 */
export async function streamQuery(
  query: string,
  cb: StreamCallbacks,
  signal?: AbortSignal
): Promise<void> {
  let res: Response;
  try {
    res = await apiStreamFetch("/api/v1/query/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, session_id: getSessionId() }),
      signal,
    });
  } catch {
    cb.onError(
      "Could not reach the LawFlow backend. Is the API running?"
    );
    return;
  }

  if (res.status === 401) {
    cb.onError("Your session has expired. Please sign in again.");
    return;
  }
  if (!res.ok || !res.body) {
    cb.onError(`Request failed (HTTP ${res.status})`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminated = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const parsed = parseSSEFrame(frame);
        if (!parsed) continue;

        if (parsed.event === "meta") {
          cb.onMeta(parsed.data as StreamMeta);
        } else if (parsed.event === "token") {
          cb.onToken((parsed.data as { text: string }).text);
        } else if (parsed.event === "done") {
          terminated = true;
          cb.onDone();
          return;
        } else if (parsed.event === "error") {
          terminated = true;
          cb.onError((parsed.data as { message: string }).message);
          return;
        }
      }
    }
    if (!terminated) cb.onDone(); // stream closed without explicit terminal
  } catch (err) {
    if ((err as Error)?.name === "AbortError") return;
    cb.onError("Streaming connection was interrupted.");
  }
}

/**
 * Flatten the backend's statute_sections into Citation cards:
 * one "provision" card for the section text, plus one "case" card per
 * referenced citation string.
 */
export function sectionsToCitations(
  sections: StatuteSection[]
): Citation[] {
  const citations: Citation[] = [];

  sections.forEach((s, i) => {
    citations.push({
      id: `sec-${i}`,
      type: "provision",
      title: `Section ${s.number} — ${s.title}`,
      citation: `Section ${s.number}`,
      court: "Central Act",
      excerpt: s.content.trim(),
    });

    s.citations.forEach((raw, j) => {
      const title = raw.split(",")[0].trim();
      const isSC = /\bSC\b|Supreme Court/i.test(raw);
      const year = raw.match(/\b(1[89]\d{2}|20\d{2})\b/)?.[1];
      citations.push({
        id: `sec-${i}-cite-${j}`,
        type: "case",
        title,
        citation: raw.trim(),
        court: isSC ? "Supreme Court of India" : "Court",
        year,
      });
    });
  });

  return citations;
}
