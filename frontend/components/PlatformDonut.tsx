"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { fmtNum } from "@/lib/format";

const COLORS = [
  "var(--accent-violet)",
  "var(--accent-cyan)",
  "var(--accent-amber)",
  "var(--accent-pink)",
  "var(--accent-emerald)",
];

export function PlatformDonut({
  data,
}: {
  data: { platform: string; label: string; sessions: number }[];
}) {
  return (
    <div className="flex items-center gap-6">
      <div className="h-44 w-44 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="sessions"
              nameKey="label"
              innerRadius={48}
              outerRadius={72}
              paddingAngle={3}
              stroke="var(--surface)"
            >
              {data.map((entry, i) => (
                <Cell key={entry.platform} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "var(--surface-raised)",
                border: "1px solid var(--border)",
                borderRadius: 12,
                color: "var(--foreground)",
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="space-y-2 text-sm">
        {data.map((entry, i) => (
          <li key={entry.platform} className="flex items-center gap-2">
            <span
              aria-hidden
              className="h-2.5 w-2.5 rounded-full"
              style={{ background: COLORS[i % COLORS.length] }}
            />
            <span>{entry.label}</span>
            <span className="text-muted">{fmtNum(entry.sessions)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
