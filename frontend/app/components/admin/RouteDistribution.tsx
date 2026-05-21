"use client";

import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

/** Lock in route → color mapping so the chart legend matches the chat UI. */
const ROUTE_COLORS: Record<string, string> = {
  deterministic: "#16A34A",  // emerald — matches chat nav indicator
  rag: "#C9892A",            // gold — matches "RAG orchestration" label
  conversation: "#0A1628",   // deep navy — neutral chat path
  fallback: "#94A3B8",       // slate — anything unmapped
};

const FALLBACK_COLOR = "#94A3B8";

interface RouteDistributionProps {
  /** Map of route → count. May be empty when no queries have flowed yet. */
  counts: Record<string, number>;
}

export function RouteDistribution({ counts }: RouteDistributionProps) {
  const data = Object.entries(counts)
    .map(([route, value]) => ({ route, value }))
    .sort((a, b) => b.value - a.value);

  if (data.length === 0) {
    return (
      <div className="flex h-[180px] items-center justify-center text-[12px] text-slate-400">
        No queries recorded yet.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="route"
          innerRadius={48}
          outerRadius={78}
          paddingAngle={2}
          strokeWidth={1}
          stroke="#fff"
          isAnimationActive
        >
          {data.map((entry) => (
            <Cell
              key={entry.route}
              fill={ROUTE_COLORS[entry.route] ?? FALLBACK_COLOR}
            />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            backgroundColor: "#0A1628",
            border: "1px solid rgba(201,137,42,0.4)",
            borderRadius: 8,
            fontSize: 12,
            color: "white",
          }}
          itemStyle={{ color: "white" }}
          labelStyle={{ color: "#D8A849", fontWeight: 600 }}
          formatter={(value, name) => [`${value} queries`, String(name)]}
        />
        <Legend
          iconType="circle"
          iconSize={8}
          formatter={(value: string) => (
            <span className="text-[11.5px] text-slate-600">{value}</span>
          )}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
