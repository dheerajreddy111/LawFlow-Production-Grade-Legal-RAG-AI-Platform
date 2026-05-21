"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { TimeseriesRow } from "../../lib/admin/api";

/**
 * Stacked area chart of query volume per route over time. Routes that
 * never fired in the window are still passed in `routes` so the legend
 * is stable across refreshes — recharts silently no-ops on zero series.
 */
const ROUTE_COLORS: Record<string, string> = {
  deterministic: "#16A34A",
  rag: "#C9892A",
  conversation: "#0A1628",
  unknown: "#94A3B8",
  fallback: "#94A3B8",
};

const ROUTE_FALLBACK = "#94A3B8";

function tickFmt(value: string): string {
  // value is an ISO 8601 timestamp from the bucket start.
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

interface VolumeAreaProps {
  routes: string[];
  data: TimeseriesRow[];
}

export function VolumeArea({ routes, data }: VolumeAreaProps) {
  if (data.length === 0 || routes.length === 0) {
    return (
      <div className="flex h-[260px] items-center justify-center text-[12px] text-slate-400">
        No queries recorded in the selected window.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
        <defs>
          {routes.map((route) => {
            const color = ROUTE_COLORS[route] ?? ROUTE_FALLBACK;
            return (
              <linearGradient
                id={`grad-${route}`}
                key={route}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop offset="0%" stopColor={color} stopOpacity={0.45} />
                <stop offset="100%" stopColor={color} stopOpacity={0.05} />
              </linearGradient>
            );
          })}
        </defs>
        <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="ts"
          stroke="#94A3B8"
          tickLine={false}
          axisLine={{ stroke: "#E2E8F0" }}
          tick={{ fontSize: 11, fill: "#64748B" }}
          tickFormatter={tickFmt}
          minTickGap={32}
        />
        <YAxis
          allowDecimals={false}
          stroke="#94A3B8"
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 11, fill: "#64748B" }}
        />
        <Tooltip
          cursor={{ stroke: "rgba(201,137,42,0.25)", strokeWidth: 1 }}
          contentStyle={{
            backgroundColor: "#0A1628",
            border: "1px solid rgba(201,137,42,0.4)",
            borderRadius: 8,
            fontSize: 12,
            color: "white",
          }}
          itemStyle={{ color: "white" }}
          labelStyle={{ color: "#D8A849", fontWeight: 600 }}
          labelFormatter={(label) => tickFmt(String(label))}
        />
        <Legend
          iconType="circle"
          iconSize={8}
          formatter={(value: string) => (
            <span className="text-[11.5px] text-slate-600">{value}</span>
          )}
        />
        {routes.map((route) => {
          const color = ROUTE_COLORS[route] ?? ROUTE_FALLBACK;
          return (
            <Area
              key={route}
              type="monotone"
              dataKey={route}
              stackId="routes"
              stroke={color}
              strokeWidth={1.5}
              fill={`url(#grad-${route})`}
              isAnimationActive
            />
          );
        })}
      </AreaChart>
    </ResponsiveContainer>
  );
}
