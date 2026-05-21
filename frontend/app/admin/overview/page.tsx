"use client";

import {
  BarChart3,
  FileStack,
  Gauge,
  MessagesSquare,
  RefreshCcw,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { IngestionBars } from "../../components/admin/IngestionBars";
import { RouteDistribution } from "../../components/admin/RouteDistribution";
import { SectionCard } from "../../components/admin/SectionCard";
import { StatCard } from "../../components/admin/StatCard";
import { fetchOverview, type OverviewResponse } from "../../lib/admin/api";

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins ? `${hours}h ${mins}m` : `${hours}h`;
  }
  return `${Math.floor(seconds / 86400)}d`;
}

export default function AdminOverviewPage() {
  const [data, setData] = useState<OverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (silent: boolean) => {
    if (silent) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const overview = await fetchOverview();
      setData(overview);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Could not load overview metrics.";
      setError(message);
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

  const queries = data?.queries;
  const latency = data?.latency;
  const docs = data?.documents;
  const users = data?.users;
  const ingestion = data?.ingestion;

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-5 py-6 sm:px-8 sm:py-8">
      {/* Page header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-[#9E6A0E]">
            Overview
          </p>
          <h1 className="mt-1.5 font-display text-[28px] font-semibold leading-tight tracking-tight text-[#0A1628]">
            Operational snapshot
          </h1>
          <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-slate-500">
            Headline metrics across ingestion, routing, retrieval, and users.
            Refreshes are explicit — readings reflect the moment of fetch.
          </p>
        </div>
        <button
          type="button"
          onClick={() => load(true)}
          disabled={refreshing || loading}
          className="inline-flex items-center gap-1.5 self-start rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-700 transition-colors hover:border-[#C9892A]/40 hover:text-[#0A1628] disabled:cursor-not-allowed disabled:opacity-60 sm:self-auto"
        >
          <RefreshCcw
            className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
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

      {/* KPI strip */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total queries"
          value={queries?.total ?? null}
          icon={MessagesSquare}
          loading={loading}
          tone="accent"
          hint={
            latency
              ? `p50 ${latency.p50_ms.toFixed(0)}ms · p95 ${latency.p95_ms.toFixed(0)}ms`
              : null
          }
        />
        <StatCard
          label="Documents indexed"
          value={docs?.total ?? null}
          icon={FileStack}
          loading={loading}
          hint={
            docs
              ? `${docs.chunks_active.toLocaleString()} active chunks · ${docs.chunks_total.toLocaleString()} total`
              : null
          }
        />
        <StatCard
          label="Active users"
          value={users?.active ?? null}
          icon={Users}
          loading={loading}
          hint={users ? `${users.admins} admin · ${users.total} total` : null}
        />
        <StatCard
          label="Avg query latency"
          value={latency?.mean_ms ?? null}
          unit="ms"
          decimals={0}
          icon={Gauge}
          loading={loading}
          hint={
            latency && latency.count > 0
              ? `${latency.count.toLocaleString()} samples`
              : "Awaiting samples"
          }
        />
      </div>

      {/* Charts row */}
      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard
          title="Route distribution"
          subtitle="Deterministic resolutions vs. RAG retrievals vs. conversation."
        >
          {loading ? (
            <ChartSkeleton />
          ) : (
            <RouteDistribution counts={queries?.by_route ?? {}} />
          )}
        </SectionCard>
        <SectionCard
          title="Ingestion by format"
          subtitle="Counts since process start."
        >
          {loading ? (
            <ChartSkeleton />
          ) : (
            <IngestionBars byExtension={ingestion?.by_extension ?? {}} />
          )}
        </SectionCard>
      </div>

      {/* Process meta */}
      <SectionCard
        title="Process"
        subtitle="In-process counters reset on restart. For persistent observability, see LangSmith traces."
        actions={
          <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            <BarChart3 className="h-3 w-3" aria-hidden />
            Live
          </span>
        }
      >
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-[12.5px] sm:grid-cols-4">
          <div>
            <dt className="text-slate-500">Uptime</dt>
            <dd className="mt-0.5 font-display text-[15px] font-semibold text-[#0A1628]">
              {data ? formatUptime(data.uptime_seconds) : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">p50 latency</dt>
            <dd className="mt-0.5 font-display text-[15px] font-semibold text-[#0A1628]">
              {latency ? `${latency.p50_ms.toFixed(0)} ms` : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">p95 latency</dt>
            <dd className="mt-0.5 font-display text-[15px] font-semibold text-[#0A1628]">
              {latency ? `${latency.p95_ms.toFixed(0)} ms` : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">p99 latency</dt>
            <dd className="mt-0.5 font-display text-[15px] font-semibold text-[#0A1628]">
              {latency ? `${latency.p99_ms.toFixed(0)} ms` : "—"}
            </dd>
          </div>
        </dl>
      </SectionCard>
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="lf-shimmer h-[220px] w-full rounded-lg bg-slate-100" />
  );
}
