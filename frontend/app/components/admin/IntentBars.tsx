"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { IntentCount } from "../../lib/admin/api";

interface IntentBarsProps {
  data: IntentCount[];
}

export function IntentBars({ data }: IntentBarsProps) {
  if (data.length === 0) {
    return (
      <div className="flex h-[220px] items-center justify-center text-[12px] text-slate-400">
        No intents recorded in this window.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 6, right: 12, bottom: 0, left: 4 }}
      >
        <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" horizontal={false} />
        <XAxis
          type="number"
          allowDecimals={false}
          stroke="#94A3B8"
          tickLine={false}
          axisLine={{ stroke: "#E2E8F0" }}
          tick={{ fontSize: 11, fill: "#64748B" }}
        />
        <YAxis
          type="category"
          dataKey="intent"
          stroke="#94A3B8"
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 11, fill: "#0A1628", fontFamily: "var(--font-mono)" }}
          width={150}
        />
        <Tooltip
          cursor={{ fill: "rgba(201,137,42,0.07)" }}
          contentStyle={{
            backgroundColor: "#0A1628",
            border: "1px solid rgba(201,137,42,0.4)",
            borderRadius: 8,
            fontSize: 12,
            color: "white",
          }}
          itemStyle={{ color: "white" }}
          labelStyle={{ color: "#D8A849", fontWeight: 600 }}
          formatter={(value) => [`${value}`, "Queries"]}
        />
        <Bar dataKey="count" fill="#0A1628" radius={[0, 4, 4, 0]} maxBarSize={18} />
      </BarChart>
    </ResponsiveContainer>
  );
}
