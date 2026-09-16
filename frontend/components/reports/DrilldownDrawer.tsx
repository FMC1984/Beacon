"use client";

/** One drawer for every Reports summary card. It fetches the rows the card
 * was computed from (same window, same source) and shows the totals next to
 * them, so a headline number can always be checked against its own
 * evidence. A card with no resolver says so instead of showing nothing. */

import { useEffect, useState } from "react";
import { fmtNum, fmtPct } from "@/lib/format";
import { API_BASE } from "@/lib/api";
import { EvidenceDrawerShell } from "./EvidenceDrawer";
import { StateBadge } from "./DataStates";
import type { DataStateKey } from "@/lib/reports";

export type DrilldownData =
  | { available: false; card: string; reason: string }
  | {
      available: true;
      card: string;
      property_name: string;
      source: string;
      window: { start: string; end: string; days: number };
      state: DataStateKey;
      columns: string[];
      group: string;
      totals: Record<string, number | null>;
      items: Record<string, unknown>[];
      total_rows: number;
      observatory_metric?: string;
    };

export function fetchDrilldown(propertyId: number, card: string, days: number): Promise<DrilldownData> {
  const params = new URLSearchParams({ property_id: String(propertyId), card, days: String(days) });
  return fetch(`${API_BASE}/reports/drilldown?${params}`, { cache: "no-store" }).then((r) => {
    if (!r.ok) throw new Error(`Drilldown failed (${r.status}).`);
    return r.json();
  });
}

const RATE_COLUMNS = new Set(["ctr", "engagement_rate"]);
const LABELS: Record<string, string> = {
  query: "Query", clicks: "Clicks", impressions: "Impressions", ctr: "CTR", position: "Position",
  source: "Source", medium: "Medium", sessions: "Sessions", engaged: "Engaged", key_events: "Key events",
  engagement_rate: "Engagement", landing_page: "Landing page", city: "City", region: "Region",
  ai_sessions: "AI sessions", component: "Component", score: "Score", weight: "Weight",
  explanation: "Explanation", priority: "#", title: "Action", state: "State", impact: "Impact",
  effort: "Effort", observed_at: "Date", prompt: "Prompt", platform: "Platform", mention_rank: "Position",
  cited: "Cited", sentiment: "Sentiment",
};

function cell(col: string, v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") {
    if (RATE_COLUMNS.has(col)) return fmtPct(v);
    if (col === "weight") return fmtPct(v);
    if (col === "position") return v.toFixed(1);
    return fmtNum(v);
  }
  return String(v);
}

export function DrilldownDrawer({
  propertyId,
  card,
  label,
  days,
  onClose,
}: {
  propertyId: number;
  card: string;
  label: string;
  days: number;
  onClose: () => void;
}) {
  const [data, setData] = useState<DrilldownData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchDrilldown(propertyId, card, days)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [propertyId, card, days]);

  return (
    <EvidenceDrawerShell open loading={!data && !error} onClose={onClose} ariaLabel={`${label} drilldown`}>
      <h2 className="text-lg font-semibold tracking-tight">{label}</h2>
      {error && <p className="mt-2 text-sm text-pink-a">{error}</p>}
      {data && !data.available && (
        <p className="mt-2 text-sm text-muted">{data.reason}</p>
      )}
      {data && data.available && (
        <>
          <p className="mt-1 text-xs text-muted">
            {data.source} · {data.window.start} to {data.window.end} · grouped by {data.group.toLowerCase()}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(data.totals).map(([k, v]) => (
              <span key={k} className="rounded-full border border-line bg-surface-raised px-2.5 py-0.5 text-[11px]">
                <span className="text-muted">{(LABELS[k] ?? k).toLowerCase()} </span>
                {cell(k, v)}
              </span>
            ))}
            {data.state !== "complete" && <StateBadge state={data.state} />}
          </div>
          {data.items.length === 0 ? (
            <p className="mt-4 text-sm text-muted">No rows in this window.</p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted">
                  <tr className="border-b border-line">
                    {data.columns.map((c) => (
                      <th key={c} className="py-1.5 pr-3 font-normal">{LABELS[c] ?? c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row, i) => (
                    <tr key={i} className="border-b border-line/50 align-top">
                      {data.columns.map((c) => (
                        <td key={c} className={`py-1.5 pr-3 ${c === "explanation" || c === "title" || c === "prompt" ? "max-w-xs" : "whitespace-nowrap"}`}>
                          {cell(c, row[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.total_rows > data.items.length && (
                <p className="mt-2 text-[11px] text-muted">
                  Showing {data.items.length} of {data.total_rows} rows.
                </p>
              )}
            </div>
          )}
          {data.observatory_metric && (
            <p className="mt-3 text-[11px] text-muted">
              Each row is one monitored AI answer. Open AI Visibility for the full answer text and citations.
            </p>
          )}
        </>
      )}
    </EvidenceDrawerShell>
  );
}
