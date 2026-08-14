"use client";

/** AI Share of Voice dashboard KPI card (Phase 18B) - the first dashboard
 * card that links straight into a full Reports detail page. Property-scoped
 * only (Share of Voice is never portfolio-aggregated, matching the
 * Competitor Intelligence and GEO precedent). Shows current Share of Voice,
 * competitive rank, and the period-over-period change in PERCENTAGE POINTS
 * ("+6 pts"), never a relative percentage on top of a percentage. */

import Link from "next/link";
import { useEffect, useState } from "react";
import { fmtPct } from "@/lib/format";
import { fetchSovKpi, type SovKpi } from "@/lib/reports";

export function useSovKpi(propertyId: number | null) {
  const [kpi, setKpi] = useState<SovKpi | null>(null);

  useEffect(() => {
    if (propertyId === null) {
      setKpi(null);
      return;
    }
    let cancelled = false;
    fetchSovKpi(propertyId)
      .then((k) => !cancelled && setKpi(k))
      .catch(() => !cancelled && setKpi(null));
    return () => {
      cancelled = true;
    };
  }, [propertyId]);

  return kpi;
}

export function SovKpiCard({ propertyId, kpi }: { propertyId: number; kpi: SovKpi }) {
  if (!kpi.has_competitors) {
    return (
      <Link
        href={`/reports/share-of-voice?property_id=${propertyId}`}
        className="block rounded-2xl border border-line bg-surface p-5 transition-colors hover:bg-surface-raised"
      >
        <p className="text-sm text-muted">AI Share of Voice</p>
        <p className="mt-1 text-sm text-muted">{kpi.message}</p>
      </Link>
    );
  }

  const pointChange = kpi.comparison.point_change;
  const changeText =
    pointChange !== null ? `${pointChange > 0 ? "+" : ""}${Math.round(pointChange * 100)} pts` : null;
  const changeClass =
    kpi.comparison.direction === "up"
      ? "text-emerald-a"
      : kpi.comparison.direction === "down"
      ? "text-pink-a"
      : "text-muted";

  return (
    <Link
      href={`/reports/share-of-voice?property_id=${propertyId}`}
      className="block rounded-2xl border border-line bg-surface p-5 transition-colors hover:bg-surface-raised"
    >
      <p className="text-sm text-muted">AI Share of Voice</p>
      {kpi.sufficient && kpi.share_of_voice !== null ? (
        <>
          <p className="mt-1 text-3xl font-semibold tracking-tight">{fmtPct(kpi.share_of_voice)}</p>
          <div className="mt-1 flex items-center gap-2 text-xs">
            {kpi.rank_label && <span className="text-muted">{kpi.rank_label}{kpi.tied ? " (tied)" : ""}</span>}
            {changeText && <span className={changeClass}>{changeText}</span>}
          </div>
        </>
      ) : (
        <p className="mt-2 text-sm text-muted">
          {kpi.sample_size} tested response(s); below the visibility sample minimum.
        </p>
      )}
    </Link>
  );
}
