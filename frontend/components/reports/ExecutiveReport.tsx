"use client";

/** Executive report (Phase 16C): metric cards, a deterministic cited
 * narrative, and the top three prioritized actions. Every narrative sentence
 * links to the report or page where its evidence lives. */

import { useEffect, useState } from "react";
import Link from "next/link";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import {
  fetchExecutiveReport,
  type ExecAction,
  type ExecCard,
  type ExecNarrativeItem,
  type ExecutiveReport as ExecReportData,
} from "@/lib/reports";
import { EmptyState, ErrorState } from "./DataStates";
import { ReportMetricCard } from "./ReportMetricCard";
import { useReportContext } from "./ReportContext";

function execCardValue(c: ExecCard): string | undefined {
  if (c.value === null) return undefined;
  if (c.unit === "pct") return fmtPct(c.value);
  if (c.key === "content_score") return String(c.value);
  return fmtNum(c.value);
}

export function ExecutiveNarrative({ items }: { items: ExecNarrativeItem[] }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <h3 className="text-sm font-medium">Summary</h3>
      <ul className="mt-3 space-y-3">
        {items.map((item, i) => (
          <li key={i} className="text-sm leading-relaxed">
            <p>{item.text}</p>
            {(item.evidence.length > 0 || item.link) && (
              <p className="mt-1 text-xs text-muted">
                {item.evidence.length > 0 && (
                  <span>Evidence: {item.evidence.join("; ")}. </span>
                )}
                <Link
                  href={item.link.href}
                  className="text-violet-a hover:underline"
                >
                  {item.link.label}
                </Link>
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function TopActions({ actions }: { actions: ExecAction[] }) {
  if (actions.length === 0) {
    return (
      <EmptyState
        title="No prioritized actions yet"
        body="The Opportunity Engine has no actionable recommendations for this property yet."
      />
    );
  }
  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <h3 className="text-sm font-medium">Top actions</h3>
      <ol className="mt-3 space-y-3">
        {actions.map((a, i) => (
          <li key={i} className="rounded-xl border border-line bg-surface-raised p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium">
                {i + 1}. {a.title}
              </p>
              <Link
                href="/opportunities"
                className="shrink-0 text-xs text-violet-a hover:underline"
              >
                View
              </Link>
            </div>
            {a.explanation && (
              <p className="mt-1 text-sm text-muted">{a.explanation}</p>
            )}
            <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted">
              {a.impact && (
                <span className="rounded-full border border-line px-2 py-0.5">
                  Impact: {a.impact}
                </span>
              )}
              {a.effort && (
                <span className="rounded-full border border-line px-2 py-0.5">
                  Effort: {a.effort}
                </span>
              )}
              <span className="rounded-full border border-line px-2 py-0.5">
                {a.supporting_signal_count} supporting signal
                {a.supporting_signal_count === 1 ? "" : "s"}
              </span>
              {a.source_modules.map((m) => (
                <span key={m} className="rounded-full border border-line px-2 py-0.5">
                  {m}
                </span>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function ExecutiveReport() {
  const { scope, days, compare } = useReportContext();
  const [data, setData] = useState<ExecReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchExecutiveReport(scope.propertyId, days, compare)
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
  }, [scope.propertyId, days, compare, attempt]);

  if (error) {
    return <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />;
  }
  if (!data) return <p className="text-sm text-muted">Loading executive report...</p>;

  if (data.scope_required) {
    return (
      <EmptyState
        title="Select a property"
        body={data.message}
      />
    );
  }

  return (
    <div className="space-y-6">
      <p className="text-xs text-muted">
        {data.property_name} · {fmtDate(data.window.start)} to{" "}
        {fmtDate(data.window.end)}
        {compare &&
          ` · compared with ${fmtDate(data.previous_window.start)} to ${fmtDate(
            data.previous_window.end
          )}`}
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {data.cards.map((c) => (
          <ReportMetricCard
            key={c.key}
            label={c.label}
            state={c.state}
            stateDetail={c.detail ?? undefined}
            value={execCardValue(c)}
            comparison={compare ? c.comparison : null}
            formatValue={(n) =>
              c.unit === "pct"
                ? fmtPct(n)
                : c.key === "content_score"
                ? String(n)
                : fmtNum(n)
            }
            higherIsBetter={c.higher_is_better}
            source={c.source}
            lastDataDate={c.last_data_date}
          />
        ))}
      </div>

      <ExecutiveNarrative items={data.narrative} />
      <TopActions actions={data.top_actions} />
    </div>
  );
}
