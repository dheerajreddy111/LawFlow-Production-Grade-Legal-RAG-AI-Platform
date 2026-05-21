"use client";

import {
  AlertOctagon,
  CheckCircle2,
  Clock,
  Loader2,
  RefreshCcw,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { SectionCard } from "../../components/admin/SectionCard";
import { cn } from "../../lib/cn";
import {
  getJob,
  listJobs,
  type JobOut,
  type JobStatus,
} from "../../lib/admin/api";

const STATUS_BADGE: Record<
  JobStatus,
  { label: string; tone: string; Icon: typeof CheckCircle2 }
> = {
  queued: {
    label: "Queued",
    tone: "bg-slate-100 text-slate-700 ring-slate-200",
    Icon: Clock,
  },
  running: {
    label: "Running",
    tone: "bg-[#FBF1DC] text-[#9E6A0E] ring-[#E8C97A]/70",
    Icon: Loader2,
  },
  completed: {
    label: "Completed",
    tone: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    Icon: CheckCircle2,
  },
  failed: {
    label: "Failed",
    tone: "bg-red-50 text-red-700 ring-red-200",
    Icon: AlertOctagon,
  },
};

function formatTs(value: string | null): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return value;
  }
}

function formatDuration(job: JobOut): string {
  if (!job.started_at) return "—";
  const end = job.completed_at ? new Date(job.completed_at) : new Date();
  const start = new Date(job.started_at);
  const ms = end.getTime() - start.getTime();
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

export default function AdminJobsPage() {
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<JobOut | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const load = useCallback(
    async (silent: boolean) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const data = await listJobs(100);
        setJobs(data.jobs);
        // If a job is selected and got refreshed, replace its state so the
        // detail panel reflects status transitions live.
        setSelected((current) => {
          if (!current) return null;
          const updated = data.jobs.find((j) => j.id === current.id);
          return updated ?? current;
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load jobs.");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!cancelled) await load(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  // Live tail — refresh every 3s while at least one job is non-terminal,
  // OR whenever the operator toggled auto-refresh on. Stops when nothing
  // is in flight so we aren't hammering the DB.
  const hasInflight = useMemo(
    () => jobs.some((j) => j.status === "queued" || j.status === "running"),
    [jobs],
  );

  useEffect(() => {
    if (!autoRefresh) return;
    if (!hasInflight) return;
    const interval = setInterval(() => {
      void load(true);
    }, 3000);
    return () => clearInterval(interval);
  }, [autoRefresh, hasInflight, load]);

  // Manually load detail when selection changes — `selected` from listJobs
  // doesn't include the full payload/result for older jobs (the list
  // endpoint and the detail endpoint return the same shape today, but a
  // future change could trim list rows; this future-proofs the panel).
  useEffect(() => {
    if (!selected) return;
    if (selected.payload !== null || selected.result !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const fresh = await getJob(selected.id);
        if (!cancelled) setSelected(fresh);
      } catch {
        /* swallow — the row from the list view is still useful */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-5 py-6 sm:px-8 sm:py-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-[#9E6A0E]">
            Jobs
          </p>
          <h1 className="mt-1.5 font-display text-[28px] font-semibold leading-tight tracking-tight text-[#0A1628]">
            Background work
          </h1>
          <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-slate-500">
            Async evaluation runs, ingestion sweeps, and retention jobs. The
            list auto-refreshes while something is in flight.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[12px] text-slate-600">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="h-3 w-3 accent-[#C9892A]"
            />
            Auto-refresh
          </label>
          <button
            type="button"
            onClick={() => load(true)}
            disabled={refreshing || loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-700 transition-colors hover:border-[#C9892A]/40 hover:text-[#0A1628] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCcw
              className={cn("h-3.5 w-3.5", refreshing && "animate-spin")}
              aria-hidden
            />
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50/80 px-4 py-3 text-[12.5px] text-red-700"
        >
          {error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        {/* List */}
        <SectionCard
          title="Recent jobs"
          subtitle={
            loading
              ? "Loading…"
              : `${jobs.length} entries${
                  hasInflight ? " · live tail" : ""
                }`
          }
        >
          {loading ? (
            <div className="lf-shimmer h-32 rounded-lg bg-slate-100" />
          ) : jobs.length === 0 ? (
            <p className="text-[12.5px] text-slate-400">
              No background jobs have run yet.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {jobs.map((j) => {
                const cfg = STATUS_BADGE[j.status];
                const active = selected?.id === j.id;
                return (
                  <li key={j.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(j)}
                      className={cn(
                        "flex w-full items-start gap-3 px-2.5 py-2.5 text-left transition-colors",
                        active
                          ? "bg-slate-50 ring-1 ring-[#C9892A]/40"
                          : "hover:bg-slate-50/60",
                      )}
                    >
                      <span
                        className={cn(
                          "mt-0.5 inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] ring-1",
                          cfg.tone,
                        )}
                      >
                        <cfg.Icon
                          className={cn(
                            "h-2.5 w-2.5",
                            j.status === "running" && "animate-spin",
                          )}
                          aria-hidden
                        />
                        {cfg.label}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-display text-[13px] font-semibold text-[#0A1628]">
                          {j.type}
                          <span className="ml-1.5 font-mono text-[11px] font-normal text-slate-400">
                            #{j.id}
                          </span>
                        </p>
                        <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
                          <span>created {formatTs(j.created_at)}</span>
                          {j.started_at && <span>· {formatDuration(j)}</span>}
                        </p>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </SectionCard>

        {/* Detail */}
        <SectionCard
          title={selected ? `Job #${selected.id}` : "Select a job"}
          subtitle={selected ? selected.type : "Detail will appear here"}
        >
          {selected ? <JobDetail job={selected} /> : (
            <p className="text-[12.5px] text-slate-400">
              Click any row to inspect its payload, result, and timeline.
            </p>
          )}
        </SectionCard>
      </div>
    </div>
  );
}

function JobDetail({ job }: { job: JobOut }) {
  const cfg = STATUS_BADGE[job.status];
  return (
    <div className="space-y-3.5 text-[12px]">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] ring-1",
            cfg.tone,
          )}
        >
          <cfg.Icon
            className={cn(
              "h-2.5 w-2.5",
              job.status === "running" && "animate-spin",
            )}
            aria-hidden
          />
          {cfg.label}
        </span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10.5px] text-slate-600">
          {job.type}
        </span>
        {job.status === "running" || job.status === "queued" ? (
          <span className="ml-auto text-[10.5px] text-slate-500">
            polling live…
          </span>
        ) : null}
      </div>

      <dl className="grid grid-cols-3 gap-2 rounded-lg bg-slate-50/60 p-2.5 ring-1 ring-slate-100">
        <Stat label="Created" value={formatTs(job.created_at)} />
        <Stat label="Started" value={formatTs(job.started_at)} />
        <Stat label="Ended" value={formatTs(job.completed_at)} />
        <Stat label="Duration" value={formatDuration(job)} />
        <Stat label="Has payload" value={job.payload ? "yes" : "no"} />
        <Stat label="Has result" value={job.result ? "yes" : "no"} />
      </dl>

      {job.error && (
        <div className="rounded-lg border border-red-200 bg-red-50/80 px-3 py-2 text-[12px] text-red-700">
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-red-600">
            Error
          </p>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-[1.55]">
            {job.error}
          </pre>
        </div>
      )}

      {job.result && (
        <KVBlock label="Result" value={job.result} />
      )}

      {job.payload && (
        <KVBlock label="Payload" value={job.payload} preview />
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        {label}
      </p>
      <p className="mt-0.5 truncate font-mono text-[11px] font-semibold text-[#0A1628]">
        {value}
      </p>
    </div>
  );
}

function KVBlock({
  label,
  value,
  preview,
}: {
  label: string;
  value: Record<string, unknown>;
  preview?: boolean;
}) {
  const json = JSON.stringify(value, null, 2);
  // If the payload contains a base64 csv (the evaluation_run shape) we
  // truncate it for display — the full bytes aren't useful here.
  const trimmed = preview
    ? JSON.stringify(
        Object.fromEntries(
          Object.entries(value).map(([k, v]) =>
            typeof v === "string" && v.length > 80
              ? [k, `${v.slice(0, 80)}… (${v.length} chars)`]
              : [k, v],
          ),
        ),
        null,
        2,
      )
    : json;
  return (
    <div>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        {label}
      </p>
      <pre className="max-h-72 overflow-auto rounded-lg bg-[#0A1628] p-3 font-mono text-[10.5px] leading-[1.55] text-[#D8E0EE]">
        {trimmed}
      </pre>
    </div>
  );
}
