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

interface IngestionBarsProps {
  /** Map of file extension → ingestion count. */
  byExtension: Record<string, number>;
}

export function IngestionBars({ byExtension }: IngestionBarsProps) {
  const data = Object.entries(byExtension)
    .map(([ext, count]) => ({ ext: ext.toUpperCase(), count }))
    .sort((a, b) => b.count - a.count);

  if (data.length === 0) {
    return (
      <div className="flex h-[180px] items-center justify-center text-[12px] text-slate-400">
        No ingestion activity yet.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -16 }}>
        <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="ext"
          stroke="#94A3B8"
          tickLine={false}
          axisLine={{ stroke: "#E2E8F0" }}
          tick={{ fontSize: 11, fill: "#64748B" }}
        />
        <YAxis
          allowDecimals={false}
          stroke="#94A3B8"
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 11, fill: "#64748B" }}
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
          formatter={(value) => [`${value}`, "Ingested"]}
        />
        <Bar
          dataKey="count"
          fill="#C9892A"
          radius={[4, 4, 0, 0]}
          maxBarSize={32}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
