/** Report metric card with optional previous-period comparison (Phase 16A).
 *
 * When the metric's data state is anything other than "complete", the card
 * shows the state label instead of a number; missing data never renders as
 * zero. Comparison figures render only when the backend declared the periods
 * comparable (a null comparison means "not compared", not "no change"). */

import type { Comparison, DataStateKey, PointComparison } from "@/lib/reports";
import { FreshnessFooter, StateBadge } from "./DataStates";

function Arrow({ direction }: { direction: "up" | "down" | "flat" }) {
  const d =
    direction === "up"
      ? "M12 19V5M5 12l7-7 7 7"
      : direction === "down"
      ? "M12 5v14M19 12l-7 7-7-7"
      : "M5 12h14";
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-3.5 w-3.5"
      aria-hidden
    >
      <path d={d} />
    </svg>
  );
}

export function ReportMetricCard({
  label,
  state,
  stateDetail,
  value,
  comparison,
  changeMode = "pct",
  formatValue,
  higherIsBetter = true,
  source,
  lastDataDate,
  sample,
  subText,
}: {
  label: string;
  state: DataStateKey;
  /** Short explanation shown when state is not "complete". */
  stateDetail?: string;
  /** Preformatted display value; only rendered when state is "complete". */
  value?: string;
  comparison?: Comparison | PointComparison | null;
  /** "points" renders a PointComparison as "+6 pts" (for comparing two
   * already-percentage metrics, e.g. Share of Voice) instead of the default
   * relative-% formatting, which would misleadingly read "+23%". */
  changeMode?: "pct" | "points";
  /** Formats comparison numbers (previous value and change). */
  formatValue?: (n: number) => string;
  /** Colors the change: for metrics like avg position, lower is better. */
  higherIsBetter?: boolean;
  source?: string;
  lastDataDate?: string | null;
  sample?: { numerator: number; denominator: number; unit: string };
  /** Preformatted explanatory line under the value, for metrics whose sample
   * does not fit the "X of Y" subset phrasing (e.g. event counts that can
   * exceed one per session). */
  subText?: string;
}) {
  const fmt = formatValue ?? ((n: number) => String(n));
  const complete = state === "complete";
  const pointComparison = changeMode === "points" ? (comparison as PointComparison | null) : null;
  const pctComparison = changeMode === "pct" ? (comparison as Comparison | null) : null;

  let changeText: string | null = null;
  let changeClass = "text-muted";
  let changeDirection: "up" | "down" | "flat" | null = null;
  if (complete && pointComparison && pointComparison.point_change !== null) {
    const pts = Math.round(pointComparison.point_change * 100);
    changeText = `${pts > 0 ? "+" : ""}${pts} pts`;
    changeDirection = pointComparison.direction;
  } else if (complete && pctComparison && pctComparison.change !== null) {
    const pct =
      pctComparison.pct_change !== null
        ? ` (${pctComparison.pct_change > 0 ? "+" : ""}${(pctComparison.pct_change * 100).toFixed(1)}%)`
        : "";
    const sign = pctComparison.change > 0 ? "+" : pctComparison.change < 0 ? "-" : "";
    changeText = `${sign}${fmt(Math.abs(pctComparison.change))}${pct}`;
    changeDirection = pctComparison.direction;
  }
  if (changeDirection && changeDirection !== "flat") {
    const improved = (changeDirection === "up") === higherIsBetter;
    changeClass = improved ? "text-emerald-a" : "text-pink-a";
  }
  const previous = comparison?.previous ?? null;
  const notComparable = complete && comparison != null && changeText === null;

  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-muted">{label}</p>
        {!complete && <StateBadge state={state} />}
      </div>

      {complete ? (
        <>
          <p className="mt-1 text-3xl font-semibold tracking-tight">{value}</p>
          {comparison &&
            (changeText !== null ? (
              <p className={`mt-1 flex items-center gap-1 text-xs ${changeClass}`}>
                {changeDirection && <Arrow direction={changeDirection} />}
                {changeText}
                {changeMode === "pct" && previous !== null && (
                  <span className="text-muted">
                    vs {fmt(previous)} previous
                  </span>
                )}
              </p>
            ) : notComparable ? (
              <p className="mt-1 text-xs text-muted">
                Previous period not comparable.
              </p>
            ) : null)}
          {sample && (
            <p className="mt-1 text-xs text-muted">
              {sample.numerator} of {sample.denominator} {sample.unit}
            </p>
          )}
          {subText && <p className="mt-1 text-xs text-muted">{subText}</p>}
        </>
      ) : (
        <p className="mt-2 text-sm text-muted">
          {stateDetail ?? "No value is shown because the data is not available."}
        </p>
      )}

      {source && (
        <FreshnessFooter source={source} lastDataDate={lastDataDate ?? null} />
      )}
    </div>
  );
}
