"use client";

/** Competitive ranking + Winners/Losers panel (Phase 18B). Reuses the
 * proportional horizontal-bar-list pattern from GeoReport's CompetitorShare/
 * SourceLandscape. Ties are shown explicitly (never silently broken), and
 * winners/losers only render when the backend has enough data to compare
 * two periods - never a fabricated "winner". */

import { useEffect, useState } from "react";
import { fmtPct } from "@/lib/format";
import { fetchSovRanking, type SovRanking, type SovWinnersLosers } from "@/lib/reports";
import { EmptyState } from "./DataStates";

function RankingBars({ ranking }: { ranking: Extract<SovRanking, { has_competitors: true }> }) {
  if (!ranking.sufficient) {
    return <EmptyState title="Not enough data to rank" body="Ranking needs more tested responses to clear the minimum sample." />;
  }
  const max = Math.max(...ranking.entities.map((e) => e.mentions), 1);
  return (
    <ul className="space-y-2">
      {ranking.entities.map((e) => (
        <li key={e.name} className="flex items-center gap-3 text-sm">
          <span className="w-8 shrink-0 text-xs text-muted">
            {e.rank !== null ? `#${e.rank}` : "—"}
          </span>
          <span className={`w-44 shrink-0 truncate ${e.is_property ? "font-medium text-foreground" : ""}`} title={e.name}>
            {e.name}
            {e.is_property && <span className="ml-1 text-xs text-violet-a">(you)</span>}
          </span>
          <div className="h-5 flex-1 rounded bg-surface-raised">
            <div
              className={`h-5 rounded ${e.is_property ? "bg-violet-a/70" : "bg-amber-a/60"}`}
              style={{ width: `${(e.mentions / max) * 100}%` }}
              role="img"
              aria-label={`${e.name}: ${e.mentions} mentions`}
            />
          </div>
          <span className="w-10 text-right">{e.mentions}</span>
          <span className="w-14 text-right text-xs text-muted">
            {e.share_of_voice !== null ? fmtPct(e.share_of_voice) : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

function WinnersLosers({ wl }: { wl: SovWinnersLosers }) {
  if (!wl.sufficient) {
    return <p className="text-sm text-muted">{wl.message ?? "Not enough data yet for winners and losers."}</p>;
  }
  const items: { label: string; text: string }[] = [];
  if (wl.biggest_gain) {
    const pts = Math.round(wl.biggest_gain.point_change * 100);
    items.push({ label: "Biggest gain", text: `Your Share of Voice is up ${pts} pts vs the previous period.` });
  }
  if (wl.biggest_loss) {
    const pts = Math.round(Math.abs(wl.biggest_loss.point_change) * 100);
    items.push({ label: "Biggest loss", text: `Your Share of Voice is down ${pts} pts vs the previous period.` });
  }
  if (wl.fastest_growing_competitor) {
    const pts = Math.round(wl.fastest_growing_competitor.point_change * 100);
    items.push({
      label: "Fastest-growing competitor",
      text: `${wl.fastest_growing_competitor.name} gained ${pts} pts vs the previous period.`,
    });
  }
  if (wl.largest_competitive_gap) {
    items.push({
      label: "Largest competitive gap",
      text: `${wl.largest_competitive_gap.name} leads you by ${fmtPct(wl.largest_competitive_gap.gap)} of Share of Voice.`,
    });
  }
  if (items.length === 0) {
    return <p className="text-sm text-muted">No notable movement this period.</p>;
  }
  return (
    <ul className="space-y-2">
      {items.map((it, i) => (
        <li key={i} className="rounded-xl border border-line p-3 text-sm">
          <p className="text-xs font-medium uppercase tracking-wider text-muted">{it.label}</p>
          <p className="mt-1">{it.text}</p>
        </li>
      ))}
    </ul>
  );
}

export function SovRankingPanel({
  propertyId,
  days,
  onClose,
}: {
  propertyId: number;
  days: number;
  onClose: () => void;
}) {
  const [data, setData] = useState<{ ranking: SovRanking; winners_losers: SovWinnersLosers } | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSovRanking(propertyId, days)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setData(null));
    return () => {
      cancelled = true;
    };
  }, [propertyId, days]);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-line bg-surface p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Competitive ranking"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-medium">Competitive ranking</h3>
          <button onClick={onClose} aria-label="Close ranking" className="text-muted hover:text-foreground">
            ✕ Close
          </button>
        </div>
        {!data ? (
          <p className="text-sm text-muted">Loading ranking...</p>
        ) : !data.ranking.has_competitors ? (
          <EmptyState title="No competitors configured" body="Add competitors to see a ranking." />
        ) : (
          <div className="space-y-6">
            <RankingBars ranking={data.ranking} />
            <div>
              <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">Winners and losers</h4>
              <WinnersLosers wl={data.winners_losers} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
