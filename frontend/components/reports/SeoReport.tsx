"use client";

/** SEO Performance report (Phase 16B). Every section renders its own data
 * state; a section without data explains itself instead of showing zeros. */

import { useEffect, useState } from "react";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import {
  fetchSeoReport,
  type SeoCard,
  type SeoMover,
  type SeoQuadrantPoint,
  type SeoReport as SeoReportData,
} from "@/lib/reports";
import { EventsPanel } from "@/components/EventsPanel";
import { EmptyState, ErrorState, StateBadge } from "./DataStates";
import { ReportMetricCard } from "./ReportMetricCard";
import { SeoQuadrantChart, SeoTrendChart } from "./SeoCharts";
import { useReportContext } from "./ReportContext";

function Section({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h3 className="text-sm font-medium">{title}</h3>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function SectionState({ state, detail }: { state: string; detail?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-dashed border-line p-4">
      <StateBadge state={state as never} />
      <p className="text-sm text-muted">{detail ?? "No data to show for this range."}</p>
    </div>
  );
}

function cardValue(c: SeoCard): string | undefined {
  if (c.value === null) return undefined;
  if (c.unit === "pct") return fmtPct(c.value);
  if (c.key === "avg_position") return c.value.toFixed(1);
  return fmtNum(c.value);
}

function MoversTable({ title, rows }: { title: string; rows: SeoMover[] }) {
  return (
    <div className="min-w-0 flex-1">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">
        {title}
      </h4>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">None above the change thresholds.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-muted">
                <th className="py-2 pr-3 font-medium">Query</th>
                <th className="py-2 pr-3 text-right font-medium">Clicks</th>
                <th className="py-2 pr-3 text-right font-medium">Impressions</th>
                <th className="py-2 text-right font-medium">Position</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.query} className="border-b border-line/50">
                  <td className="max-w-[16rem] truncate py-2 pr-3" title={m.query}>
                    {m.query}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    {m.current_clicks ?? "n/a"}
                    <span
                      className={`ml-1.5 text-xs ${
                        m.click_change > 0
                          ? "text-emerald-a"
                          : m.click_change < 0
                          ? "text-pink-a"
                          : "text-muted"
                      }`}
                    >
                      {m.click_change > 0 ? "+" : ""}
                      {m.click_change}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right">
                    {m.current_impressions ?? "n/a"}
                    <span className="ml-1.5 text-xs text-muted">
                      {m.impression_change > 0 ? "+" : ""}
                      {m.impression_change}
                    </span>
                  </td>
                  <td className="py-2 text-right">
                    {m.current_position ?? "n/a"}
                    {m.position_change !== null && (
                      <span
                        className={`ml-1.5 text-xs ${
                          m.position_change < 0
                            ? "text-emerald-a"
                            : m.position_change > 0
                            ? "text-pink-a"
                            : "text-muted"
                        }`}
                      >
                        {m.position_change > 0 ? "+" : ""}
                        {m.position_change}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const FLAG_LABELS: Record<string, string> = {
  high_impressions_low_ctr: "High impressions, low CTR",
  striking_distance: "Striking distance (8-20)",
  strong_rank_low_clicks: "Strong rank, few clicks",
  declining: "Declining",
};

export function SeoReport() {
  const { scope, days, compare } = useReportContext();
  const [data, setData] = useState<SeoReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<SeoQuadrantPoint | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    setSelected(null);
    fetchSeoReport(scope, days, compare)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.propertyId, scope.companyId, scope.unassigned, days, compare, attempt]);

  if (error) {
    return <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />;
  }
  if (!data) return <p className="text-sm text-muted">Loading SEO report...</p>;

  const warnings = [
    ...new Set(
      data.summary.cards
        .map((c) => c.comparison_warning)
        .filter((w): w is string => Boolean(w))
    ),
  ];

  return (
    <div className="space-y-6">
      <p className="text-xs text-muted">
        {fmtDate(data.window.start)} to {fmtDate(data.window.end)}
        {data.window.anchored_to_latest_data && " · window anchored to latest data"}
        {compare &&
          ` · compared with ${fmtDate(data.previous_window.start)} to ${fmtDate(
            data.previous_window.end
          )}`}
      </p>

      {warnings.map((w) => (
        <div
          key={w}
          className="rounded-xl border border-amber-a/40 bg-amber-a/10 px-4 py-2.5 text-sm text-amber-a"
        >
          {w}
        </div>
      ))}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {data.summary.cards.map((c) => (
          <ReportMetricCard
            key={c.key}
            label={c.label}
            state={c.state}
            stateDetail={
              c.state === "not_configured"
                ? "Source not connected."
                : c.state === "empty"
                ? "No rows in this range."
                : undefined
            }
            value={cardValue(c)}
            comparison={compare ? c.comparison : null}
            formatValue={(n) =>
              c.unit === "pct"
                ? fmtPct(n)
                : c.key === "avg_position"
                ? n.toFixed(1)
                : fmtNum(n)
            }
            higherIsBetter={c.higher_is_better}
            source={c.source}
            lastDataDate={c.last_data_date}
            sample={
              c.sample
                ? {
                    numerator: c.sample.numerator,
                    denominator: c.sample.denominator,
                    unit: c.key === "ctr" ? "impressions clicked" : "sessions converting",
                  }
                : undefined
            }
          />
        ))}
      </div>

      <Section title="Search performance trends" sub="Search Console, daily. Days without data appear as gaps, not zeros.">
        {data.trends.state !== "complete" ? (
          <SectionState state={data.trends.state} />
        ) : (
          <SeoTrendChart series={data.trends.series} />
        )}
      </Section>

      <Section title="Ranking distribution" sub={data.ranking_distribution.note}>
        {data.ranking_distribution.state !== "complete" ? (
          <SectionState
            state={data.ranking_distribution.state}
            detail={data.ranking_distribution.detail}
          />
        ) : (
          <div>
            <p className="mb-3 text-xs text-muted">
              {fmtNum(data.ranking_distribution.total_queries!.current)} imported queries
              {data.ranking_distribution.total_queries!.previous !== null &&
                ` · ${fmtNum(
                  data.ranking_distribution.total_queries!.previous
                )} in the previous period`}
            </p>
            <ul className="space-y-2">
              {data.ranking_distribution.buckets.map((b) => {
                const max = Math.max(
                  1,
                  ...data.ranking_distribution.buckets.map((x) => x.current)
                );
                return (
                  <li key={b.bucket} className="flex items-center gap-3 text-sm">
                    <span className="w-14 shrink-0 text-muted">{b.bucket}</span>
                    <div className="h-5 flex-1 rounded bg-surface-raised">
                      <div
                        className="h-5 rounded bg-cyan-a/70"
                        style={{ width: `${(b.current / max) * 100}%` }}
                        role="img"
                        aria-label={`${b.bucket}: ${b.current} queries`}
                      />
                    </div>
                    <span className="w-10 text-right">{b.current}</span>
                    <span className="w-14 text-right text-xs text-muted">
                      {b.change === null
                        ? ""
                        : `${b.change > 0 ? "+" : ""}${b.change}`}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </Section>

      <Section
        title="Search opportunity quadrant"
        sub="Bubble size is clicks. Click a bubble for query details."
      >
        {data.quadrant.state !== "complete" ? (
          <SectionState state={data.quadrant.state} detail={data.quadrant.detail} />
        ) : (
          <div>
            <SeoQuadrantChart points={data.quadrant.points} onSelect={setSelected} />
            {selected && (
              <div className="mt-3 rounded-xl border border-line bg-surface-raised p-4 text-sm">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-medium">{selected.query}</p>
                  <button
                    onClick={() => setSelected(null)}
                    aria-label="Close query details"
                    className="text-muted hover:text-foreground"
                  >
                    ✕
                  </button>
                </div>
                <p className="mt-1 text-xs text-muted">
                  Position {selected.position} · {fmtNum(selected.impressions)}{" "}
                  impressions · {fmtNum(selected.clicks)} clicks
                  {selected.ctr !== null && ` · CTR ${fmtPct(selected.ctr)}`} ·{" "}
                  {selected.branded ? "branded" : "non-branded"}
                </p>
                {selected.pages.length > 0 && (
                  <p className="mt-1 text-xs text-muted">
                    Pages: {selected.pages.join(", ")}
                  </p>
                )}
                {Object.entries(selected.flags).some(([, v]) => v) && (
                  <p className="mt-1 text-xs text-amber-a">
                    {Object.entries(selected.flags)
                      .filter(([, v]) => v)
                      .map(([k]) => FLAG_LABELS[k])
                      .join(" · ")}
                  </p>
                )}
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
              {Object.entries(data.quadrant.highlights ?? {}).map(([k, n]) => (
                <span
                  key={k}
                  className="rounded-full border border-line px-2.5 py-0.5"
                  title={data.quadrant.rules?.[k]}
                >
                  {FLAG_LABELS[k]}: {n}
                </span>
              ))}
              {(data.quadrant.dropped ?? 0) > 0 && (
                <span className="rounded-full border border-amber-a/40 px-2.5 py-0.5 text-amber-a">
                  {data.quadrant.dropped} lower-impression queries not plotted
                </span>
              )}
            </div>
          </div>
        )}
      </Section>

      <Section
        title="Biggest gains and declines"
        sub={
          data.movers.thresholds
            ? `Queries with at least ${data.movers.thresholds.min_impressions} impressions and a change of ${data.movers.thresholds.min_click_change}+ clicks or ${data.movers.thresholds.min_position_change}+ positions.`
            : undefined
        }
      >
        {data.movers.state !== "complete" ? (
          <SectionState state={data.movers.state} detail={data.movers.detail} />
        ) : (
          <div className="flex flex-col gap-6 lg:flex-row">
            <MoversTable title="Gains" rows={data.movers.gains} />
            <MoversTable title="Declines" rows={data.movers.losses} />
          </div>
        )}
      </Section>

      <Section title="Landing page performance" sub={data.landing_pages.normalization}>
        {data.landing_pages.state !== "complete" ? (
          <SectionState
            state={data.landing_pages.state}
            detail={data.landing_pages.detail}
          />
        ) : data.landing_pages.rows.length === 0 ? (
          <EmptyState title="No pages" body="No page-level rows in this range." />
        ) : (
          <div>
            {data.landing_pages.match_counts && (
              <p className="mb-3 text-xs text-muted">
                {data.landing_pages.match_counts.matched} matched ·{" "}
                {data.landing_pages.match_counts.ga4_only} GA4 only ·{" "}
                {data.landing_pages.match_counts.gsc_only} Search Console only
                {(data.landing_pages.dropped ?? 0) > 0 &&
                  ` · ${data.landing_pages.dropped} more rows not shown`}
              </p>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-muted">
                    <th className="py-2 pr-3 font-medium">Page</th>
                    <th className="py-2 pr-3 text-right font-medium">Sessions</th>
                    <th className="py-2 pr-3 text-right font-medium">Engaged</th>
                    <th className="py-2 pr-3 text-right font-medium">Key events</th>
                    <th className="py-2 pr-3 text-right font-medium">Conv. rate</th>
                    <th className="py-2 pr-3 text-right font-medium">Clicks</th>
                    <th className="py-2 text-right font-medium">Impressions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.landing_pages.rows.map((r) => (
                    <tr key={r.page} className="border-b border-line/50">
                      <td className="max-w-[18rem] truncate py-2 pr-3" title={r.page}>
                        {r.page}
                        {!r.matched && (
                          <span className="ml-2 rounded-full border border-line px-1.5 text-[10px] text-muted">
                            unmatched
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-right">
                        {r.sessions !== null ? fmtNum(r.sessions) : "n/a"}
                      </td>
                      <td className="py-2 pr-3 text-right">
                        {r.engaged_sessions !== null ? fmtNum(r.engaged_sessions) : "n/a"}
                      </td>
                      <td className="py-2 pr-3 text-right">
                        {r.key_events !== null ? fmtNum(r.key_events) : "n/a"}
                      </td>
                      <td className="py-2 pr-3 text-right">
                        {r.conversion_rate !== null ? fmtPct(r.conversion_rate) : "n/a"}
                      </td>
                      <td className="py-2 pr-3 text-right">
                        {r.clicks !== null ? fmtNum(r.clicks) : "n/a"}
                      </td>
                      <td className="py-2 text-right">
                        {r.impressions !== null ? fmtNum(r.impressions) : "n/a"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Section>

      {data.events && <EventsPanel section={data.events} title="Events" />}
    </div>
  );
}
