"use client";

/** Honest placeholder for a report tab whose build phase has not landed yet,
 * plus the live source-status panel used by the Executive tab. Placeholders
 * never show fabricated numbers. */

import { useEffect, useState } from "react";
import {
  fetchReportStatus,
  type ReportStatus,
  type ReportTab,
} from "@/lib/reports";
import { fmtDate } from "@/lib/format";
import { ErrorState, StateBadge } from "./DataStates";
import { useReportContext } from "./ReportContext";

export function PlannedReport({ tab }: { tab: ReportTab }) {
  const deferred = tab.planned_phase === "deferred";
  return (
    <div className="rounded-2xl border border-dashed border-line bg-surface/50 p-8">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold tracking-tight">{tab.label}</h2>
        <span className="rounded-full border border-violet-a/40 bg-violet-a/10 px-2.5 py-0.5 text-[11px] font-medium text-violet-a">
          {deferred ? "Deferred" : `Planned for Phase ${tab.planned_phase}`}
        </span>
      </div>
      <p className="mt-2 max-w-2xl text-sm text-muted">{tab.summary}</p>
      <p className="mt-4 text-xs text-muted">
        This tab is a placeholder. Nothing on it is computed yet, and no
        numbers are shown until the real calculations exist.
      </p>
    </div>
  );
}

export function SourceStatusPanel() {
  const { scope } = useReportContext();
  const [status, setStatus] = useState<ReportStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus(null);
    setError(null);
    fetchReportStatus(scope)
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.propertyId, scope.companyId, scope.unassigned, attempt]);

  if (error) {
    return (
      <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />
    );
  }

  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Data sources</h3>
        {status && (
          <span className="text-xs text-muted">
            Checked {fmtDate(status.checked_date)}
          </span>
        )}
      </div>
      {!status ? (
        <p className="mt-3 text-sm text-muted">Loading source status...</p>
      ) : (
        <ul className="mt-3 divide-y divide-line/60">
          {status.sources.map((s) => (
            <li key={s.key} className="flex items-center justify-between gap-3 py-2.5">
              <div>
                <p className="text-sm">{s.label}</p>
                <p className="text-xs text-muted">{s.detail}</p>
              </div>
              <StateBadge state={s.state} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
