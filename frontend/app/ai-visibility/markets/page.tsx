"use client";

import { useState } from "react";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { UsagePanel } from "@/components/observatory/IntelligencePanels";
import { DataLabelBadge, LoadState, Panel, ShareBar, useLoad } from "@/components/observatory/ui";
import { fetchMarkets, fetchMarketSummary, fmtRate } from "@/lib/observatory";

export default function MarketsPage() {
  const { property, days, setPropertyId } = useObservatory();
  const markets = useLoad(() => fetchMarkets(), []);
  // A manual market choice is remembered only while the property's market is unchanged.
  const [choice, setChoice] = useState<{ forMarket: number | null | undefined; id: number } | null>(null);
  const marketId = choice && choice.forMarket === property?.market_id ? choice.id : null;

  const list = markets.data?.markets ?? [];
  const fallbackId = property?.market_id ?? list.find((m) => m.property_count > 0)?.id ?? list[0]?.id ?? null;
  const selectedId = marketId ?? fallbackId;

  const summary = useLoad(selectedId === null ? null : () => fetchMarketSummary(selectedId, days), [selectedId, days]);

  return (
    <div className="space-y-6">
      <UsagePanel days={days} propertyId={property?.id ?? null} />
      <LoadState
        loading={markets.loading && !markets.data}
        error={markets.error}
        retry={markets.retry}
        empty={{ when: markets.data !== null && list.length === 0, title: "No markets yet", body: "Markets are created from each property's city and state." }}
      >
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm">
            <span className="mr-2 text-muted">Market</span>
            <select
              value={selectedId ?? ""}
              onChange={(e) => setChoice({ forMarket: property?.market_id, id: Number(e.target.value) })}
              className="rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
            >
              {list.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.property_count} propert{m.property_count === 1 ? "y" : "ies"})
                </option>
              ))}
            </select>
          </label>
        </div>

        <LoadState loading={summary.loading && !summary.data} error={summary.error} retry={summary.retry}>
          {summary.data && (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                {[
                  ["Shared market runs", summary.data.runs],
                  ["Shared answers stored", summary.data.responses],
                  ["Property scores from shared answers", summary.data.properties_scored],
                  ["Citations in shared answers", summary.data.citations],
                ].map(([label, n]) => (
                  <div key={label} className="rounded-2xl border border-line bg-surface p-5">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm text-muted">{label}</p>
                      <DataLabelBadge label="MEASURED" />
                    </div>
                    <p className="mt-1 text-3xl font-semibold tracking-tight">{n}</p>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted">{summary.data.note}</p>

              <Panel
                title={`${summary.data.market.name} leaderboard`}
                label="MEASURED"
                subtitle="AI Visibility per property from every answer it was scored on (shared market answers and its own brand runs). Below the minimum sample shows n/a."
              >
                {summary.data.leaderboard.length === 0 ? (
                  <p className="text-sm text-muted">No active properties in this market.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[560px] text-sm">
                      <thead className="text-left text-xs text-muted">
                        <tr className="border-b border-line">
                          <th className="py-2 pr-3 font-normal">Property</th>
                          <th className="w-56 py-2 pr-3 font-normal">AI Visibility</th>
                          <th className="py-2 pr-3 text-right font-normal">Citation Rate</th>
                          <th className="py-2 pr-3 text-right font-normal">Share of Voice</th>
                          <th className="py-2 text-right font-normal">Responses</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.data.leaderboard.map((r) => (
                          <tr key={r.property_id} className={`border-b border-line/60 ${r.property_id === property?.id ? "bg-violet-a/5" : ""}`}>
                            <td className="py-2 pr-3">
                              <button onClick={() => setPropertyId(r.property_id)} className="text-left hover:text-violet-a">
                                {r.name}
                              </button>
                            </td>
                            <td className="py-2 pr-3">
                              <div className="flex items-center gap-2">
                                <ShareBar value={r.ai_visibility} />
                                <span className="w-10 shrink-0 text-right text-xs">{fmtRate(r.ai_visibility)}</span>
                              </div>
                            </td>
                            <td className="py-2 pr-3 text-right">{fmtRate(r.citation_rate)}</td>
                            <td className="py-2 pr-3 text-right">{fmtRate(r.share_of_voice)}</td>
                            <td className="py-2 text-right text-muted">{r.eligible_responses}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </>
          )}
        </LoadState>
      </LoadState>
    </div>
  );
}
