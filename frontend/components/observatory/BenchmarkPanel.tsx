"use client";

/** The property's four headline metrics beside the average of the other
 * monitored properties Beacon holds (all, and the same segment). Pools are
 * never named; below the pool minimum the column reads UNAVAILABLE with
 * the reason. Sample communities compare only with sample ones. */

import { fetchBenchmark, fmtRate, type BenchmarkRow } from "@/lib/observatory";
import { DataLabelBadge, LoadState, Panel, useLoad } from "./ui";

const LABELS: Record<string, string> = {
  ai_visibility: "AI Visibility",
  citation_rate: "Citation Rate",
  share_of_voice: "Share of Voice",
  recommendation_rate: "Recommendation Rate",
};

function Delta({ row }: { row: BenchmarkRow }) {
  if (row.point_change === null) return <span className="text-xs text-muted">n/a</span>;
  const pts = Math.round(row.point_change * 100);
  const cls = pts > 0 ? "text-emerald-300" : pts < 0 ? "text-amber-300" : "text-muted";
  return <span className={`text-xs ${cls}`}>{pts > 0 ? "+" : ""}{pts} pts</span>;
}

function PoolTable({ title, pool, metrics }: { title: string; pool: { properties: number; organizations: number }; metrics: Record<string, BenchmarkRow> }) {
  return (
    <div>
      <h3 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">{title}</h3>
      <p className="mb-2 text-[11px] text-muted">
        {pool.properties > 0 ? `${pool.properties} other propert${pool.properties === 1 ? "y" : "ies"} across ${pool.organizations} organization${pool.organizations === 1 ? "" : "s"}` : "No pool yet"}
      </p>
      <table className="w-full text-sm">
        <thead className="text-left text-[11px] text-muted">
          <tr><th className="py-1 font-normal">Metric</th><th className="py-1 text-right font-normal">You</th><th className="py-1 text-right font-normal">Others</th><th className="py-1 text-right font-normal">Gap</th></tr>
        </thead>
        <tbody>
          {Object.entries(metrics).map(([k, r]) => (
            <tr key={k} className="border-t border-line/60 align-top">
              <td className="py-1.5 pr-2">{LABELS[k] ?? k}</td>
              <td className="py-1.5 text-right tabular-nums">{r.property_value !== null ? fmtRate(r.property_value) : <span className="text-muted">n/a</span>}</td>
              <td className="py-1.5 text-right tabular-nums">
                {r.benchmark_value !== null ? fmtRate(r.benchmark_value) : (
                  <span className="text-xs text-muted" title={r.note ?? undefined}><DataLabelBadge label="UNAVAILABLE" /></span>
                )}
              </td>
              <td className="py-1.5 text-right"><Delta row={r} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BenchmarkPanel({ propertyId, days }: { propertyId: number; days: number }) {
  const { data, error, loading, retry } = useLoad(() => fetchBenchmark(propertyId, days), [propertyId, days]);
  const firstNote = data ? Object.values(data.all.metrics).find((r) => r.note)?.note : null;
  return (
    <Panel
      title="Compared with other communities"
      label="MEASURED"
      subtitle="Your numbers beside the average of the other properties Beacon monitors. Pools count only properties with enough answers in this window and are never named."
    >
      <LoadState loading={loading && !data} error={error} retry={retry}>
        {data && (
          <>
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <PoolTable title="All other properties" pool={data.all.pool} metrics={data.all.metrics} />
              <PoolTable
                title={data.segment ? `Same type (${data.segment.replace(/_/g, " ")})` : "Same type"}
                pool={data.segment_pool.pool}
                metrics={data.segment_pool.metrics}
              />
            </div>
            <p className="mt-3 text-xs text-muted">{firstNote ?? data.note}</p>
          </>
        )}
      </LoadState>
    </Panel>
  );
}
