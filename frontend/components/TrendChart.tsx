"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtShortDate } from "@/lib/format";

export function TrendChart({
  data,
}: {
  data: { date: string; sessions: number; ai_sessions: number }[];
}) {
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <defs>
            <linearGradient id="sessionsFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent-cyan)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--accent-cyan)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="aiFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent-violet)" stopOpacity={0.5} />
              <stop offset="100%" stopColor="var(--accent-violet)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={fmtShortDate}
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            axisLine={{ stroke: "var(--border)" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              background: "var(--surface-raised)",
              border: "1px solid var(--border)",
              borderRadius: 12,
              color: "var(--foreground)",
            }}
            labelStyle={{ color: "var(--muted)" }}
          />
          <Area
            type="monotone"
            dataKey="sessions"
            name="All sessions"
            stroke="var(--accent-cyan)"
            strokeWidth={2}
            fill="url(#sessionsFill)"
          />
          <Area
            type="monotone"
            dataKey="ai_sessions"
            name="AI sessions"
            stroke="var(--accent-violet)"
            strokeWidth={2}
            fill="url(#aiFill)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
