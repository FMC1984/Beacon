"use client";

/** Property dashboard card for the AI Visibility Observatory: AI Visibility
 * and Citation Rate for the last 30 days with percentage-point change,
 * linking into the Observatory. Below the minimum sample it says so instead
 * of showing a number. */

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchOverview, fmtRate, type ObsMetric, type Overview } from "@/lib/observatory";
import { DataLabelBadge } from "./ui";

export function useAiVisibilityOverview(propertyId: number | null) {
  const [data, setData] = useState<{ id: number; overview: Overview | null } | null>(null);
  useEffect(() => {
    if (propertyId === null) return;
    let cancelled = false;
    fetchOverview(propertyId, 30)
      .then((o) => !cancelled && setData({ id: propertyId, overview: o }))
      .catch(() => !cancelled && setData({ id: propertyId, overview: null }));
    return () => {
      cancelled = true;
    };
  }, [propertyId]);
  return propertyId !== null && data?.id === propertyId ? data.overview : null;
}

function Line({ m }: { m: ObsMetric }) {
  const pts = m.comparison?.point_change;
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-xs text-muted">{m.label}</span>
      <span className="text-sm">
        {m.value === null ? (
          <span className="text-xs text-muted">insufficient sample</span>
        ) : (
          <>
            <span className="font-semibold">{fmtRate(m.value)}</span>
            {pts !== null && pts !== undefined && (
              <span className="ml-1.5 text-xs text-muted">
                {pts > 0 ? "+" : ""}
                {Math.round(pts * 100)} pts
              </span>
            )}
          </>
        )}
      </span>
    </div>
  );
}

export function AiVisibilityBlock({ propertyId, overview }: { propertyId: number; overview: Overview }) {
  const n = overview.sample.eligible_responses;
  const empty = n === 0;
  const measured = overview.metrics.ai_visibility.value !== null || overview.metrics.citation_rate.value !== null;
  return (
    <Link
      href={`/ai-visibility?property_id=${propertyId}`}
      className="block rounded-2xl border border-line bg-surface p-5 transition-colors hover:bg-surface-raised"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-muted">AI Observatory</p>
        {measured && <DataLabelBadge label="MEASURED" />}
      </div>
      {empty ? (
        <p className="mt-2 text-sm text-muted">No AI answers monitored in the last 30 days. Open the Observatory to generate prompts.</p>
      ) : (
        <div className="mt-2 space-y-1.5">
          <Line m={overview.metrics.ai_visibility} />
          <Line m={overview.metrics.citation_rate} />
          <p className="pt-1 text-[11px] text-muted">
            {n} monitored answer{n === 1 ? "" : "s"}, last 30 days
          </p>
        </div>
      )}
    </Link>
  );
}
