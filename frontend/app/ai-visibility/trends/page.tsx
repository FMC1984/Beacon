"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { StandingPanel } from "@/components/observatory/legacy/StandingPanel";
import { DataLabelBadge, FormulaNote, LoadState, NeedsProperty, Panel, useLoad } from "@/components/observatory/ui";
import { fetchTrend, fmtRate } from "@/lib/observatory";
import { fmtShortDate } from "@/lib/format";

const METRICS: [string, string][] = [
  ["ai_visibility", "AI Visibility"],
  ["citation_rate", "Citation Rate"],
  ["citation_share", "Citation Share"],
  ["share_of_voice", "Share of Voice"],
  ["recommendation_rate", "Recommendation Rate"],
  ["competitor_win_rate", "Competitor Win Rate"],
];

export default function TrendsPage() {
  const { propertyId, days } = useObservatory();
  const [metric, setMetric] = useState("ai_visibility");
  const { data, error, loading, retry } = useLoad(
    propertyId === null ? null : () => fetchTrend(propertyId, metric, days),
    [propertyId, metric, days]
  );
  if (propertyId === null) return <NeedsProperty />;

  const pts = data?.comparison.point_change;
  return (
    <div className="space-y-6">
      <Panel
        title="Trend"
        label={data?.data_label}
        subtitle="Daily values from the rollups. Days below the minimum sample are left as gaps rather than drawn as zero."
        actions={
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            aria-label="Metric"
            className="rounded-xl border border-line bg-surface-raised px-3 py-1.5 text-sm"
          >
            {METRICS.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        }
      >
        <LoadState loading={loading && !data} error={error} retry={retry}>
          {data && (
            <>
              <div className="mb-4 flex flex-wrap items-baseline gap-x-6 gap-y-1">
                <p>
                  <span className="text-3xl font-semibold tracking-tight">{fmtRate(data.current.value)}</span>
                  <span className="ml-2 text-xs text-muted">
                    this period ({data.current.numerator} of {data.current.denominator})
                  </span>
                </p>
                <p className="text-sm text-muted">
                  Previous period {fmtRate(data.previous.value)}
                  {pts !== null && pts !== undefined && (
                    <span className="ml-2 font-medium text-foreground">
                      {pts > 0 ? "+" : ""}
                      {Math.round(pts * 100)} pts
                    </span>
                  )}
                </p>
              </div>
              {data.series.length === 0 ? (
                <p className="text-sm text-muted">No observations in this window.</p>
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data.series} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                      <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                      <XAxis
                        dataKey="day"
                        tickFormatter={fmtShortDate}
                        tick={{ fill: "var(--muted)", fontSize: 12 }}
                        axisLine={{ stroke: "var(--border)" }}
                        tickLine={false}
                      />
                      <YAxis
                        domain={[0, 1]}
                        tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                        tick={{ fill: "var(--muted)", fontSize: 12 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip
                        contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, fontSize: 12 }}
                        labelFormatter={(l) => fmtShortDate(String(l))}
                        formatter={(v, _n, item) => {
                          const p = item.payload as { numerator: number; denominator: number };
                          return [v === null ? "insufficient sample" : `${fmtRate(Number(v))} (${p.numerator} of ${p.denominator})`, data.label];
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke="var(--accent-violet)"
                        strokeWidth={2}
                        dot={{ r: 3, fill: "var(--accent-violet)" }}
                        connectNulls={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
              <div className="mt-2 flex items-center gap-2">
                <DataLabelBadge label={data.data_label} />
                <FormulaNote formula={data.current.formula} note={data.current.note} />
              </div>
            </>
          )}
        </LoadState>
      </Panel>

      <Panel title="Standing prompts and score history" subtitle="The pre-Observatory cadence prompts and directional score, kept while shared market scoring builds history.">
        <StandingPanel propertyId={propertyId} />
      </Panel>
    </div>
  );
}
