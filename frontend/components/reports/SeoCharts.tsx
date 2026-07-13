"use client";

/** Recharts pieces for the SEO Performance report (Phase 16B): the
 * metric-selectable search trend chart and the opportunity quadrant. One
 * metric per chart, never four metrics on one incompatible scale. */

import { useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { fmtNum, fmtPct, fmtShortDate } from "@/lib/format";
import type { SeoQuadrantPoint, SeoTrendPoint } from "@/lib/reports";

const METRICS = [
  { key: "clicks", label: "Clicks", color: "var(--accent-cyan)", pct: false },
  { key: "impressions", label: "Impressions", color: "var(--accent-violet)", pct: false },
  { key: "ctr", label: "CTR", color: "var(--accent-emerald)", pct: true },
  { key: "position", label: "Avg position", color: "var(--accent-amber)", pct: false },
] as const;

type MetricKey = (typeof METRICS)[number]["key"];

export function SeoTrendChart({ series }: { series: SeoTrendPoint[] }) {
  const [metric, setMetric] = useState<MetricKey>("clicks");
  const m = METRICS.find((x) => x.key === metric)!;
  // Average position: lower is better, so the axis is reversed.
  const reversed = metric === "position";
  return (
    <div>
      <div role="group" aria-label="Trend metric" className="mb-3 flex gap-1">
        {METRICS.map((x) => (
          <button
            key={x.key}
            onClick={() => setMetric(x.key)}
            aria-pressed={metric === x.key}
            className={`rounded-lg px-3 py-1 text-sm transition-colors ${
              metric === x.key
                ? "bg-surface-raised font-medium text-foreground"
                : "text-muted hover:text-foreground"
            }`}
          >
            {x.label}
          </button>
        ))}
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <defs>
              <linearGradient id="seoTrendFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={m.color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={m.color} stopOpacity={0} />
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
              reversed={reversed}
              domain={reversed ? [1, "auto"] : [0, "auto"]}
              tickFormatter={(v: number) => (m.pct ? fmtPct(v) : fmtNum(v))}
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
              formatter={(value) =>
                m.pct ? fmtPct(Number(value)) : fmtNum(Number(value))
              }
            />
            <Area
              type="monotone"
              dataKey={metric}
              name={m.label}
              stroke={m.color}
              strokeWidth={2}
              fill="url(#seoTrendFill)"
              connectNulls={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function SeoQuadrantChart({
  points,
  onSelect,
}: {
  points: SeoQuadrantPoint[];
  onSelect: (p: SeoQuadrantPoint) => void;
}) {
  const plotted = points.filter((p) => p.position !== null);
  const branded = plotted.filter((p) => p.branded);
  const nonBranded = plotted.filter((p) => !p.branded);
  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 8, left: -4, bottom: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="position"
            name="Avg position"
            reversed
            domain={[1, "auto"]}
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            axisLine={{ stroke: "var(--border)" }}
            tickLine={false}
            label={{
              value: "Average position (better to the right)",
              position: "insideBottom",
              offset: -2,
              fill: "var(--muted)",
              fontSize: 11,
            }}
          />
          <YAxis
            type="number"
            dataKey="impressions"
            name="Impressions"
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <ZAxis type="number" dataKey="clicks" range={[40, 400]} name="Clicks" />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            contentStyle={{
              background: "var(--surface-raised)",
              border: "1px solid var(--border)",
              borderRadius: 12,
              color: "var(--foreground)",
            }}
            formatter={(value, name) => [fmtNum(Number(value)), name]}
            labelFormatter={() => ""}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            content={({ active, payload }: any) => {
              if (!active || !payload?.length) return null;
              const p: SeoQuadrantPoint = payload[0].payload;
              return (
                <div className="rounded-xl border border-line bg-surface-raised p-3 text-xs">
                  <p className="mb-1 font-medium text-foreground">{p.query}</p>
                  <p className="text-muted">
                    Position {p.position} · {fmtNum(p.impressions)} impressions ·{" "}
                    {fmtNum(p.clicks)} clicks
                    {p.ctr !== null ? ` · CTR ${fmtPct(p.ctr)}` : ""}
                  </p>
                </div>
              );
            }}
          />
          <Scatter
            name="Branded"
            data={branded}
            fill="var(--accent-violet)"
            fillOpacity={0.75}
            onClick={(e) => e && onSelect(e.payload as SeoQuadrantPoint)}
          />
          <Scatter
            name="Non-branded"
            data={nonBranded}
            fill="var(--accent-cyan)"
            fillOpacity={0.75}
            onClick={(e) => e && onSelect(e.payload as SeoQuadrantPoint)}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
