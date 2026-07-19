/** Report metric card with optional previous-period comparison (Phase 16A).
 *
 * When the metric's data state is anything other than "complete", the card
 * shows the state label instead of a number; missing data never renders as
 * zero. Comparison figures render only when the backend declared the periods
 * comparable (a null comparison means "not compared", not "no change"). */

import type { Comparison, DataStateKey } from "@/lib/reports";
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
  comparison?: Comparison | null;
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

  let changeText: string | null = null;
  let changeClass = "text-muted";
  if (complete && comparison && comparison.change !== null) {
    const pct =
      comparison.pct_change !== null
        ? ` (${comparison.pct_change > 0 ? "+" : ""}${(comparison.pct_change * 100).toFixed(1)}%)`
        : "";
    const sign = comparison.change > 0 ? "+" : comparison.change < 0 ? "-" : "";
    changeText = `${sign}${fmt(Math.abs(comparison.change))}${pct}`;
    if (comparison.direction !== "flat" && comparison.direction !== null) {
      const improved = (comparison.direction === "up") === higherIsBetter;
      changeClass = improved ? "text-emerald-a" : "text-pink-a";
    }
  }

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
            (comparison.change !== null ? (
              <p className={`mt-1 flex items-center gap-1 text-xs ${changeClass}`}>
                {comparison.direction && <Arrow direction={comparison.direction} />}
                {changeText}
                {comparison.previous !== null && (
                  <span className="text-muted">
                    vs {fmt(comparison.previous)} previous
                  </span>
                )}
              </p>
            ) : (
              <p className="mt-1 text-xs text-muted">
                Previous period not comparable.
              </p>
            ))}
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
