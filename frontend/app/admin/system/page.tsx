"use client";

import { motion } from "framer-motion";
import {
  AlertOctagon,
  Brain,
  Check,
  CircleAlert,
  Cpu,
  Database,
  ExternalLink,
  HeartPulse,
  RefreshCcw,
  Sparkles,
  Terminal,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { SectionCard } from "../../components/admin/SectionCard";
import { cn } from "../../lib/cn";
import {
  fetchSystem,
  type CorpusStatusBlock,
  type CounterEntry,
  type HealthCheck,
  type LangSmithStatus,
  type LLMProvidersStatus,
  type MemoryStatus,
  type ProcessStatus,
  type SystemResponse,
  type VectorStoreStatus,
} from "../../lib/admin/api";

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return m ? `${h}h ${m}m` : `${h}h`;
  }
  return `${Math.floor(seconds / 86400)}d`;
}

export default function AdminSystemPage() {
  const [data, setData] = useState<SystemResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent: boolean) => {
    if (silent) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      setData(await fetchSystem());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load system status.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!cancelled) await load(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-5 py-6 sm:px-8 sm:py-8">
      {/* Page header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-[#9E6A0E]">
            System Health
          </p>
          <h1 className="mt-1.5 font-display text-[28px] font-semibold leading-tight tracking-tight text-[#0A1628]">
            Infrastructure & traces
          </h1>
          <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-slate-500">
            Live status of the vector store, LangSmith integration, LLM
            providers, in-process memory, and recent error counters.
            Secrets are never serialised — only presence + model names.
          </p>
        </div>
        <button
          type="button"
          onClick={() => load(true)}
          disabled={refreshing || loading}
          className="inline-flex items-center gap-1.5 self-start rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-700 transition-colors hover:border-[#C9892A]/40 hover:text-[#0A1628] disabled:cursor-not-allowed disabled:opacity-60 sm:self-auto"
        >
          <RefreshCcw
            className={cn("h-3.5 w-3.5", refreshing && "animate-spin")}
            aria-hidden
          />
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50/80 px-4 py-3 text-[12.5px] text-red-700"
        >
          {error}
        </div>
      )}

      <StatusBanner data={data} loading={loading} />

      <div className="grid gap-4 lg:grid-cols-2">
        <VectorStoreCard data={data?.vector_store ?? null} loading={loading} />
        <LangSmithCard data={data?.langsmith ?? null} loading={loading} />
        <LLMProvidersCard data={data?.llm_providers ?? null} loading={loading} />
        <MemoryCard data={data?.memory ?? null} loading={loading} />
      </div>

      <ProcessCard data={data?.process ?? null} loading={loading} />

      <CorpusReadinessCard data={data?.corpus ?? null} loading={loading} />

      <div className="grid gap-4 lg:grid-cols-2">
        <CountersCard
          title="Ingestion failures"
          subtitle="Failed parse / OCR / chunk-and-embed steps since process start."
          icon={AlertOctagon}
          empty="No ingestion failures observed."
          rows={data?.ingest_failures ?? []}
          loading={loading}
        />
        <CountersCard
          title="Recent error counters"
          subtitle="Any counter tagged with `errors.*` from in-process metrics."
          icon={CircleAlert}
          empty="No error counters incremented."
          rows={data?.error_counters ?? []}
          loading={loading}
        />
      </div>
    </div>
  );
}

// ── Status banner ─────────────────────────────────────────────────────────

function StatusBanner({
  data,
  loading,
}: {
  data: SystemResponse | null;
  loading: boolean;
}) {
  const overall = data?.status;
  const checks = data?.checks ?? [];
  const tone =
    overall === "ok"
      ? {
          bar: "from-emerald-50/60 to-white border-emerald-200",
          icon: "bg-emerald-500/15 text-emerald-700 ring-emerald-200",
          label: "All systems operational",
        }
      : overall === "degraded"
      ? {
          bar: "from-amber-50/60 to-white border-amber-200",
          icon: "bg-amber-500/15 text-amber-700 ring-amber-300",
          label: "Some subsystems degraded",
        }
      : {
          bar: "from-slate-50 to-white border-slate-200",
          icon: "bg-slate-100 text-slate-500 ring-slate-200",
          label: "Loading status…",
        };

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={cn(
        "overflow-hidden rounded-xl border bg-gradient-to-br",
        tone.bar,
      )}
    >
      <div className="flex items-center gap-3 p-4">
        <span
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-xl ring-1",
            tone.icon,
          )}
        >
          <HeartPulse className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Status
          </p>
          <p className="font-display text-[15px] font-semibold leading-tight tracking-tight text-[#0A1628]">
            {loading ? "Checking subsystems…" : tone.label}
          </p>
        </div>
      </div>
      {!loading && checks.length > 0 && (
        <ul className="grid gap-x-4 gap-y-1.5 border-t border-slate-100 bg-white/60 px-4 py-3 sm:grid-cols-3">
          {checks.map((c) => (
            <CheckRow key={c.name} check={c} />
          ))}
        </ul>
      )}
    </motion.div>
  );
}

function CheckRow({ check }: { check: HealthCheck }) {
  return (
    <li className="flex items-start gap-2 text-[12px]">
      <span
        className={cn(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full",
          check.ok
            ? "bg-emerald-500/15 text-emerald-700"
            : "bg-amber-500/20 text-amber-700",
        )}
      >
        {check.ok ? (
          <Check className="h-2.5 w-2.5" aria-hidden />
        ) : (
          <X className="h-2.5 w-2.5" aria-hidden />
        )}
      </span>
      <div className="min-w-0">
        <p className="truncate font-display text-[12.5px] font-semibold text-[#0A1628]">
          {check.name}
        </p>
        <p className="truncate text-[11.5px] text-slate-500">{check.detail}</p>
      </div>
    </li>
  );
}

// ── Subsystem cards ───────────────────────────────────────────────────────

function VectorStoreCard({
  data,
  loading,
}: {
  data: VectorStoreStatus | null;
  loading: boolean;
}) {
  return (
    <SectionCard
      title="Vector store"
      subtitle="ChromaDB collection backing semantic retrieval."
      actions={
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
          <Database className="h-3.5 w-3.5" aria-hidden />
        </span>
      }
    >
      {loading ? (
        <CardSkeleton />
      ) : !data ? (
        <Empty />
      ) : (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12.5px]">
          <KV label="Collection" value={data.collection || "—"} mono />
          <KV label="Indexed chunks" value={data.count.toLocaleString()} mono />
          <KV label="Embedding dim" value={data.embedding_dim.toString()} mono />
          <KV
            label="On disk"
            value={
              <span className="block truncate font-mono text-[11.5px] text-slate-700">
                {data.path || "—"}
              </span>
            }
          />
        </dl>
      )}
    </SectionCard>
  );
}

function LangSmithCard({
  data,
  loading,
}: {
  data: LangSmithStatus | null;
  loading: boolean;
}) {
  const projectUrl =
    data?.configured && data.project
      ? `https://smith.langchain.com/o/-/projects/p/${encodeURIComponent(data.project)}`
      : null;
  return (
    <SectionCard
      title="LangSmith tracing"
      subtitle="Per-request observability. Activates only when both LANGCHAIN_TRACING_V2 and LANGCHAIN_API_KEY are set."
      actions={
        <span
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-lg",
            data?.configured
              ? "bg-[#0A1628] text-[#D8A849]"
              : "bg-slate-100 text-slate-500",
          )}
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden />
        </span>
      }
    >
      {loading ? (
        <CardSkeleton />
      ) : !data ? (
        <Empty />
      ) : data.configured ? (
        <LangSmithActive data={data} projectUrl={projectUrl} />
      ) : (
        <LangSmithInactive data={data} />
      )}
    </SectionCard>
  );
}

function LangSmithActive({
  data,
  projectUrl,
}: {
  data: LangSmithStatus;
  projectUrl: string | null;
}) {
  // Map the startup-probe outcome to a colour band. Unknown ≠ broken
  // (we just haven't probed yet, e.g. langsmith client absent), so it
  // renders as a neutral slate rather than red.
  const probe = data.connectivity;
  const probeBand =
    probe === "ok"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
      : probe === "error"
        ? "bg-rose-50 text-rose-700 ring-rose-200"
        : "bg-slate-50 text-slate-600 ring-slate-200";
  const probeLabel =
    probe === "ok" ? "Reachable" : probe === "error" ? "Unreachable" : "Unknown";

  return (
    <div className="space-y-3 text-[12.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] text-emerald-700 ring-1 ring-emerald-200">
          Active
        </span>
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] ring-1",
            probeBand,
          )}
          title={data.connectivity_detail ?? undefined}
        >
          {probeLabel}
        </span>
        <span className="text-slate-600">
          {probe === "error"
            ? "Spans may not be delivered."
            : "Traces are streaming to LangSmith."}
        </span>
      </div>
      <KV label="Project" value={data.project} mono />
      {data.endpoint && <KV label="Endpoint" value={data.endpoint} mono />}
      {probe === "error" && data.connectivity_detail && (
        <p className="rounded-md border border-rose-200/70 bg-rose-50/70 px-2.5 py-2 font-mono text-[11px] leading-snug text-rose-700">
          {data.connectivity_detail}
        </p>
      )}
      {projectUrl && (
        <a
          href={projectUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-lg bg-[#0A1628] px-3 py-1.5 text-[11.5px] font-semibold text-[#D8A849] ring-1 ring-[#C9892A]/40 transition-colors hover:ring-[#C9892A]/60"
        >
          Open in LangSmith
          <ExternalLink className="h-3 w-3" aria-hidden />
        </a>
      )}
    </div>
  );
}

function LangSmithInactive({ data }: { data: LangSmithStatus }) {
  // Three distinguishable inactive states: both off, flag on without
  // key, key set without flag. Naming each helps an operator know which
  // env var is missing without digging through .env.
  let label = "Not configured";
  let body: React.ReactNode = (
    <p className="text-slate-500">
      Set{" "}
      <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px]">
        LANGCHAIN_TRACING_V2=true
      </code>{" "}
      and{" "}
      <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px]">
        LANGCHAIN_API_KEY
      </code>{" "}
      on the backend to enable persistent tracing.
    </p>
  );
  if (data.tracing_flag_enabled && !data.api_key_present) {
    label = "Flag on · key missing";
    body = (
      <p className="text-slate-500">
        <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px]">
          LANGCHAIN_TRACING_V2
        </code>{" "}
        is true but{" "}
        <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px]">
          LANGCHAIN_API_KEY
        </code>{" "}
        is empty. Tracing stays inactive until both are set.
      </p>
    );
  } else if (!data.tracing_flag_enabled && data.api_key_present) {
    label = "Key set · flag off";
    body = (
      <p className="text-slate-500">
        Set{" "}
        <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px]">
          LANGCHAIN_TRACING_V2=true
        </code>{" "}
        to activate tracing — the API key is already configured.
      </p>
    );
  }
  return (
    <div className="space-y-2 text-[12.5px]">
      <div className="flex items-center gap-2">
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] text-slate-600 ring-1 ring-slate-200">
          {label}
        </span>
      </div>
      {body}
    </div>
  );
}

function LLMProvidersCard({
  data,
  loading,
}: {
  data: LLMProvidersStatus | null;
  loading: boolean;
}) {
  return (
    <SectionCard
      title="LLM providers"
      subtitle="Active provider drives RAG generation. The deterministic route never calls an LLM."
      actions={
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
          <Cpu className="h-3.5 w-3.5" aria-hidden />
        </span>
      }
    >
      {loading ? (
        <CardSkeleton />
      ) : !data ? (
        <Empty />
      ) : (
        <div className="space-y-2.5">
          <div className="flex items-center gap-2 text-[12.5px]">
            <span className="text-slate-500">Active</span>
            {data.active ? (
              <span className="rounded bg-[#FBF1DC] px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] text-[#9E6A0E] ring-1 ring-[#E8C97A]/70">
                {data.active}
              </span>
            ) : (
              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] text-amber-700 ring-1 ring-amber-300">
                none
              </span>
            )}
          </div>

          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-100">
            {data.providers.map((p) => (
              <li
                key={p.name}
                className="flex items-center gap-3 px-3 py-2 text-[12.5px]"
              >
                <span
                  className={cn(
                    "h-2 w-2 rounded-full",
                    p.configured ? "bg-emerald-500" : "bg-slate-300",
                  )}
                  aria-hidden
                />
                <span className="flex-1 font-mono text-[12px] text-[#0A1628]">
                  {p.name}
                </span>
                {p.model && (
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10.5px] text-slate-600">
                    {p.model}
                  </span>
                )}
                <span
                  className={cn(
                    "text-[10.5px] font-semibold uppercase tracking-[0.12em]",
                    p.configured ? "text-emerald-700" : "text-slate-400",
                  )}
                >
                  {p.configured ? "configured" : "missing key"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </SectionCard>
  );
}

function MemoryCard({
  data,
  loading,
}: {
  data: MemoryStatus | null;
  loading: boolean;
}) {
  const usagePct = data
    ? Math.min(100, Math.round((data.sessions / Math.max(1, data.max_sessions)) * 100))
    : 0;
  return (
    <SectionCard
      title="Conversation memory"
      subtitle="In-process LRU. Sessions evict oldest-first when the cap is reached."
      actions={
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
          <Brain className="h-3.5 w-3.5" aria-hidden />
        </span>
      }
    >
      {loading ? (
        <CardSkeleton />
      ) : !data ? (
        <Empty />
      ) : (
        <div className="space-y-3">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12.5px]">
            <KV label="Active sessions" value={data.sessions.toLocaleString()} mono />
            <KV label="Turns retained" value={data.turns_total.toLocaleString()} mono />
            <KV label="Session cap" value={data.max_sessions.toLocaleString()} mono />
            <KV label="Per-session window" value={`${data.window} turns`} mono />
          </dl>
          <div>
            <div className="mb-1 flex items-center justify-between text-[10.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              <span>LRU occupancy</span>
              <span className="tabular-nums">{usagePct}%</span>
            </div>
            <div className="relative h-1.5 overflow-hidden rounded-full bg-slate-100">
              <motion.span
                initial={{ width: 0 }}
                animate={{ width: `${usagePct}%` }}
                transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                className={cn(
                  "absolute inset-y-0 left-0 rounded-full",
                  usagePct >= 90
                    ? "bg-amber-500"
                    : usagePct >= 60
                    ? "bg-[#C9892A]"
                    : "bg-emerald-500",
                )}
              />
            </div>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

function ProcessCard({
  data,
  loading,
}: {
  data: ProcessStatus | null;
  loading: boolean;
}) {
  return (
    <SectionCard
      title="Process"
      subtitle="Backend runtime — environment, Python version, and uptime since last restart."
      actions={
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
          <Terminal className="h-3.5 w-3.5" aria-hidden />
        </span>
      }
    >
      {loading ? (
        <CardSkeleton />
      ) : !data ? (
        <Empty />
      ) : (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12.5px] sm:grid-cols-4">
          <KV label="Environment" value={data.environment} mono />
          <KV label="Debug" value={data.debug ? "on" : "off"} mono />
          <KV label="Python" value={data.python_version} mono />
          <KV label="Uptime" value={formatUptime(data.uptime_seconds)} mono />
        </dl>
      )}
    </SectionCard>
  );
}

function CountersCard({
  title,
  subtitle,
  icon: Icon,
  rows,
  empty,
  loading,
}: {
  title: string;
  subtitle: string;
  icon: typeof AlertOctagon;
  rows: CounterEntry[];
  empty: string;
  loading: boolean;
}) {
  return (
    <SectionCard
      title={title}
      subtitle={subtitle}
      actions={
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
          <Icon className="h-3.5 w-3.5" aria-hidden />
        </span>
      }
    >
      {loading ? (
        <CardSkeleton />
      ) : rows.length === 0 ? (
        <p className="text-[12.5px] text-slate-500">{empty}</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-100">
          {rows.slice(0, 8).map((row) => (
            <li
              key={row.name}
              className="flex items-center gap-3 px-3 py-2 text-[12px]"
            >
              <span className="flex-1 truncate font-mono text-[11.5px] text-slate-700">
                {row.name}
              </span>
              <span className="tabular-nums font-display text-[13px] font-semibold text-[#0A1628]">
                {row.value.toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

// ── Building blocks ───────────────────────────────────────────────────────

function KV({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-0.5 truncate text-[12.5px] font-semibold text-[#0A1628]",
          mono && "font-mono text-[12px]",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function CardSkeleton() {
  return (
    <div className="space-y-2">
      <div className="lf-shimmer h-4 w-3/4 rounded bg-slate-100" />
      <div className="lf-shimmer h-4 w-1/2 rounded bg-slate-100" />
      <div className="lf-shimmer h-4 w-2/3 rounded bg-slate-100" />
    </div>
  );
}

function Empty() {
  return <p className="text-[12.5px] text-slate-400">No data available.</p>;
}


function CorpusReadinessCard({
  data,
  loading,
}: {
  data: CorpusStatusBlock | null;
  loading: boolean;
}) {
  const missing = data?.missing_keys ?? [];
  const orphan = data?.orphan_keys ?? [];
  const drift = missing.length + orphan.length > 0;

  return (
    <SectionCard
      title="Corpus readiness"
      subtitle="Registered acts vs the on-disk Chroma index. Any drift here means re-ingestion is needed."
      actions={
        <span
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-lg",
            drift
              ? "bg-amber-50 text-amber-700"
              : "bg-emerald-50 text-emerald-700",
          )}
        >
          {drift ? (
            <AlertOctagon className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <Check className="h-3.5 w-3.5" aria-hidden />
          )}
        </span>
      }
    >
      {loading ? (
        <CardSkeleton />
      ) : !data ? (
        <Empty />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-[12px] text-slate-600">
            <span className="rounded bg-emerald-50 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
              {data.indexed_keys.length}/{data.supported_keys.length} acts indexed
            </span>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-slate-600">
              {data.total_indexed_chunks.toLocaleString()} chunks
            </span>
            {missing.length > 0 && (
              <span className="rounded bg-amber-50 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-amber-800 ring-1 ring-amber-200">
                {missing.length} missing
              </span>
            )}
            {orphan.length > 0 && (
              <span className="rounded bg-rose-50 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-rose-700 ring-1 ring-rose-200">
                {orphan.length} orphan
              </span>
            )}
          </div>

          {missing.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-[12px] text-amber-800">
              <p className="font-semibold">Supported but not indexed:</p>
              <p className="mt-1 font-mono text-[11.5px]">
                {missing.join(", ")}
              </p>
              <p className="mt-1 text-[11px]">
                Operator action: re-run corpus ingestion (the lifespan
                normally does this on startup).
              </p>
            </div>
          )}

          {orphan.length > 0 && (
            <div className="rounded-lg border border-rose-200 bg-rose-50/70 px-3 py-2 text-[12px] text-rose-700">
              <p className="font-semibold">Indexed but unregistered:</p>
              <p className="mt-1 font-mono text-[11.5px]">
                {orphan.join(", ")}
              </p>
              <p className="mt-1 text-[11px]">
                These chunks no longer have a registry entry — purge or
                re-register them.
              </p>
            </div>
          )}

          <div className="overflow-hidden rounded-lg border border-slate-100">
            <table className="w-full text-[12px]">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-3 py-1.5 text-left font-semibold uppercase tracking-[0.1em] text-[10.5px] text-slate-500">
                    Act
                  </th>
                  <th className="px-3 py-1.5 text-left font-semibold uppercase tracking-[0.1em] text-[10.5px] text-slate-500">
                    Domain
                  </th>
                  <th className="px-3 py-1.5 text-right font-semibold uppercase tracking-[0.1em] text-[10.5px] text-slate-500">
                    Chunks
                  </th>
                  <th className="px-3 py-1.5 text-right font-semibold uppercase tracking-[0.1em] text-[10.5px] text-slate-500">
                    State
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.acts.map((a) => (
                  <tr
                    key={a.act_key}
                    className="border-t border-slate-100 hover:bg-slate-50/60"
                  >
                    <td className="px-3 py-1.5 font-display text-[12.5px] text-[#0A1628]">
                      {a.name}
                    </td>
                    <td className="px-3 py-1.5 text-[11.5px] text-slate-500">
                      {a.domain ?? "—"}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-slate-600">
                      {a.chunk_count.toLocaleString()}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {a.indexed ? (
                        <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-emerald-700 ring-1 ring-emerald-200">
                          <Check className="h-2.5 w-2.5" aria-hidden />
                          indexed
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-amber-800 ring-1 ring-amber-200">
                          <X className="h-2.5 w-2.5" aria-hidden />
                          missing
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </SectionCard>
  );
}
