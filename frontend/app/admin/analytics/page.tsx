"use client";

import {
  AlertOctagon,
  BarChart3,
  Gauge,
  MessagesSquare,
  PieChart,
  RefreshCcw,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { IntentBars } from "../../components/admin/IntentBars";
import { SectionCard } from "../../components/admin/SectionCard";
import { StatCard } from "../../components/admin/StatCard";
import { VolumeArea } from "../../components/admin/VolumeArea";
import { cn } from "../../lib/cn";
import {
  fetchAnalytics,
  type AnalyticsRange,
  type AnalyticsResponse,
  type FailureEntry,
} from "../../lib/admin/api";

const RANGE_OPTIONS: { value: AnalyticsRange; label: string }[] = [
  { value: "1h", label: "1 hour" },
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];

function formatRelative(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const diffMs = Date.now() - d.getTime();
    const secs = Math.max(0, Math.round(diffMs / 1000));
    if (secs < 60) return `${secs}s ago`;
    const mins = Math.round(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.round(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  } catch {
    return iso;
  }
}

export default function AdminAnalyticsPage() {
  const [range, setRange] = useState<AnalyticsRange>("24h");
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (silent: boolean, rangeKey: AnalyticsRange) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        setData(await fetchAnalytics(rangeKey));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load analytics.");
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
      if (!cancelled) await load(false, range);
    })();
    return () => {
      cancelled = true;
    };
  }, [load, range]);

  const totals = data?.totals;
  const errorRate = totals
    ? Math.round((totals.error_rate || 0) * 1000) / 10
    : null;

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-5 py-6 sm:px-8 sm:py-8">
      {/* Page header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-[#9E6A0E]">
            Analytics
          </p>
          <h1 className="mt-1.5 font-display text-[28px] font-semibold leading-tight tracking-tight text-[#0A1628]">
            Query analytics
          </h1>
          <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-slate-500">
            Aggregations over the persisted query_events log. Recorded
            per-request server-side; deterministic vs RAG breakdown is
            stacked across the window you pick.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RangePicker value={range} onChange={setRange} disabled={refreshing} />
          <button
            type="button"
            onClick={() => load(true, range)}
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

      {/* KPI strip */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Queries in window"
          value={totals?.total ?? null}
          icon={MessagesSquare}
          loading={loading}
          tone="accent"
        />
        <StatCard
          label="Avg latency"
          value={totals?.avg_latency_ms ?? null}
          unit="ms"
          decimals={0}
          icon={Gauge}
          loading={loading}
        />
        <StatCard
          label="Error rate"
          value={errorRate}
          unit="%"
          decimals={1}
          icon={errorRate !== null && errorRate > 1 ? TrendingUp : TrendingDown}
          loading={loading}
          hint={totals ? `${totals.errors} failures` : null}
        />
        <StatCard
          label="Routes active"
          value={data?.routes.length ?? null}
          icon={PieChart}
          loading={loading}
          hint={
            data
              ? Object.entries(data.route_share)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(" · ")
              : null
          }
        />
      </div>

      {/* Volume chart */}
      <SectionCard
        title="Query volume by route"
        subtitle="Stacked by deterministic / RAG / conversational route per bucket."
        actions={
          <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            <BarChart3 className="h-3 w-3" aria-hidden />
            {range}
          </span>
        }
      >
        {loading ? (
          <ChartSkeleton tall />
        ) : !data ? (
          <Empty />
        ) : (
          <VolumeArea routes={data.routes} data={data.timeseries} />
        )}
      </SectionCard>

      {/* Intent + Recent failures */}
      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard
          title="Intent distribution"
          subtitle="Counts grouped by classifier output."
        >
          {loading ? (
            <ChartSkeleton />
          ) : !data ? (
            <Empty />
          ) : (
            <IntentBars data={data.intent_distribution} />
          )}
        </SectionCard>

        <SectionCard
          title="Recent failures"
          subtitle="Latest 10 events flagged has_error. Independent of the range above."
          actions={
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
              <AlertOctagon className="h-3.5 w-3.5" aria-hidden />
            </span>
          }
        >
          {loading ? (
            <ChartSkeleton />
          ) : !data ? (
            <Empty />
          ) : data.recent_failures.length === 0 ? (
            <p className="text-[12.5px] text-slate-500">
              No failed queries on record.
            </p>
          ) : (
            <FailureList failures={data.recent_failures} />
          )}
        </SectionCard>
      </div>
    </div>
  );
}

// ── Range picker ──────────────────────────────────────────────────────────

function RangePicker({
  value,
  onChange,
  disabled,
}: {
  value: AnalyticsRange;
  onChange: (next: AnalyticsRange) => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Analytics time range"
      className={cn(
        "inline-flex items-center rounded-lg border border-slate-200 bg-white p-0.5 shadow-[inset_0_1px_0_rgba(10,22,40,0.03)]",
        disabled && "opacity-60",
      )}
    >
      {RANGE_OPTIONS.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => !active && onChange(opt.value)}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11.5px] font-semibold transition-colors",
              active
                ? "bg-[#0A1628] text-[#D8A849]"
                : "text-slate-600 hover:text-[#0A1628]",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Failure list ──────────────────────────────────────────────────────────

function FailureList({ failures }: { failures: FailureEntry[] }) {
  return (
    <ul className="divide-y divide-slate-100 rounded-lg border border-slate-100">
      {failures.map((f, i) => (
        <li key={`${f.ts}-${i}`} className="px-3 py-2.5 text-[12px]">
          <div className="flex items-start gap-2">
            <span
              className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-red-50 text-red-600 ring-1 ring-red-200"
              aria-hidden
            >
              <AlertOctagon className="h-2.5 w-2.5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-display text-[12.5px] font-semibold text-[#0A1628]">
                {f.query || "(empty query)"}
              </p>
              <p className="mt-0.5 flex items-center gap-2 text-[10.5px] text-slate-500">
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
                  {f.intent}
                </span>
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
                  {f.route}
                </span>
                <span className="ml-auto">{formatRelative(f.ts)}</span>
              </p>
              {f.error_reason && (
                <p className="mt-1 line-clamp-2 text-[11.5px] text-red-700">
                  {f.error_reason}
                </p>
              )}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

// ── Skeletons ─────────────────────────────────────────────────────────────

function ChartSkeleton({ tall }: { tall?: boolean }) {
  return (
    <div
      className={cn(
        "lf-shimmer w-full rounded-lg bg-slate-100",
        tall ? "h-[260px]" : "h-[220px]",
      )}
    />
  );
}

function Empty() {
  return <p className="text-[12.5px] text-slate-400">No data available.</p>;
}
