"use client";

/** The top of the AI Visibility overview: who AI names in this market, and
 * where this property sits.
 *
 * The ranked bars answer "how am I doing" before any metric card does, which
 * is why the separate market and comp-set tiles are gone: this says the same
 * thing with the shape included. Communities CiteRoll monitors but cannot
 * rank are counted underneath rather than dropped, because the list alone
 * cannot distinguish "too few answers" from "never named".
 */

import Link from "next/link";
import type { ObsMetric, Standing, TrendPoint } from "@/lib/observatory";
import { fetchStanding, fmtRate } from "@/lib/observatory";
import { Sparkline } from "./Sparkline";
import { DataLabelBadge, FormulaNote, useLoad } from "./ui";

function MarketRows({ market }: { market: Extract<Standing["market"], { available: true }> }) {
  const footnotes = [
    market.never_named > 0
      ? `${market.never_named} monitored ${market.never_named === 1 ? "community was" : "communities were"} not named in any answer here.`
      : null,
    market.below_sample > 0
      ? `${market.below_sample} more ${market.below_sample === 1 ? "has" : "have"} too few monitored answers to rank yet.`
      : null,
    market.also_named > 0
      ? `AI also names ${market.also_named} ${market.also_named === 1 ? "community" : "communities"} here that nobody tracks yet.`
      : null,
  ].filter(Boolean) as string[];

  return (
    <>
      <ul className="space-y-2">
        {market.ranked.map((r) => (
          <li key={r.name} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3">
            <span className={`truncate text-sm ${r.is_property ? "font-semibold text-foreground" : "text-muted"}`}>
              {r.name}
            </span>
            <span className="h-4 rounded-md bg-surface-raised">
              <span
                className={`block h-4 rounded-md ${r.is_property ? "bg-violet-a" : "bg-line"}`}
                style={{ width: `${Math.max(r.ai_visibility * 100, 1.5)}%` }}
              />
            </span>
            <span className={`shrink-0 text-sm tabular-nums ${r.is_property ? "font-semibold" : "text-muted"}`}>
              {fmtRate(r.ai_visibility)}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted">
        Share of this property&apos;s monitored answers that named each community.
      </p>
      {footnotes.map((f) => (
        <p key={f} className="mt-1 text-xs text-muted">
          {f}
        </p>
      ))}
    </>
  );
}

function CompSetLine({ compSet }: { compSet: Standing["comp_set"] }) {
  if (!compSet.available) return <span className="text-muted">{compSet.reason}</span>;
  if (compSet.rank === null) return <span className="text-muted">Not named in any monitored answer in this window.</span>;
  return (
    <span>
      <span className="font-semibold">
        #{compSet.rank} of {compSet.size}
      </span>{" "}
      <span className="text-muted">
        beating {compSet.beating} of {compSet.competitors} confirmed competitor
        {compSet.competitors === 1 ? "" : "s"}
        {compSet.tied ? ", tied" : ""}
      </span>
    </span>
  );
}

export function VisibilityHero({
  propertyId,
  days,
  metric,
  series,
  window,
  onDrill,
}: {
  propertyId: number;
  days: number;
  metric: ObsMetric;
  series: TrendPoint[];
  window: { start: string; end: string };
  onDrill?: (metric: string) => void;
}) {
  const { data } = useLoad(() => fetchStanding(propertyId, days), [propertyId, days]);
  const market = data?.market;
  const complete = metric.state === "complete" && metric.value !== null;
  const cmp = metric.comparison;
  const pts = complete && cmp && cmp.point_change !== null ? Math.round(cmp.point_change * 100) : null;
  const tone = pts === null || pts === 0 ? "text-muted" : pts > 0 ? "text-emerald-a" : "text-pink-a";

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.55fr_1fr]">
      <section className="rounded-2xl border border-line bg-surface p-5">
        <div className="mb-4 flex items-baseline justify-between gap-3">
          <h2 className="text-base font-semibold">Who AI names in this market</h2>
          <Link
            href={`/ai-visibility/markets?property_id=${propertyId}`}
            className="shrink-0 text-xs text-violet-a hover:underline"
          >
            Market view ›
          </Link>
        </div>
        {market === undefined ? (
          <p className="text-sm text-muted">Loading the market.</p>
        ) : !market.available ? (
          <p className="text-sm text-muted">{market.reason}</p>
        ) : market.only_one ? (
          <>
            <MarketRows market={market} />
            <p className="mt-2 text-xs text-muted">
              The only community CiteRoll monitors here, so there is nobody to rank against yet.
            </p>
          </>
        ) : (
          <MarketRows market={market} />
        )}
      </section>

      <section className="flex flex-col rounded-2xl border border-line bg-surface p-5">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm text-muted">{metric.label}</p>
          <DataLabelBadge label={metric.data_label} />
        </div>
        {complete ? (
          <>
            <div className="mt-1 flex items-baseline gap-2">
              <p className="text-5xl font-semibold tracking-tight tabular-nums">{fmtRate(metric.value)}</p>
              {pts !== null && (
                <span className={`text-sm ${tone}`}>
                  {pts > 0 ? "+" : ""}
                  {pts} pts
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-muted">
              {metric.numerator} of {metric.denominator} monitored responses
            </p>
            <div className="mt-3 text-violet-a">
              <Sparkline
                series={series}
                from={window.start}
                to={window.end}
                height={64}
                area
                label={`${metric.label} across the monitored days in this window`}
              />
            </div>
          </>
        ) : (
          <p className="mt-2 text-sm text-muted">
            Needs at least {metric.minimum_sample} monitored responses; {metric.denominator} so far.
          </p>
        )}
        <div className="mt-3 border-t border-line pt-3 text-sm">
          <p className="mb-1 text-xs text-muted">Comp set</p>
          {data ? <CompSetLine compSet={data.comp_set} /> : <span className="text-muted">Loading.</span>}
        </div>
        <div className="mt-auto">
          <FormulaNote formula={metric.formula} note={metric.note} />
          {onDrill && complete && (
            <button
              type="button"
              onClick={() => onDrill(metric.key)}
              aria-haspopup="dialog"
              className="mt-2 text-xs text-violet-a hover:underline"
            >
              See the answers ›
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
