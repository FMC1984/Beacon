"use client";

import { useState } from "react";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { DataLabelBadge, LoadState, Panel, ShareBar, useLoad } from "@/components/observatory/ui";
import { fetchPortfolio, fmtRate } from "@/lib/observatory";

const AVERAGES: [keyof import("@/lib/observatory").Portfolio["averages"], string][] = [
  ["ai_visibility", "AI Visibility"],
  ["citation_rate", "Citation Rate"],
  ["share_of_voice", "Share of Voice"],
  ["recommendation_rate", "Recommendation Rate"],
];

export default function PortfolioPage() {
  const { companies, property, days, setPropertyId } = useObservatory();
  const [scope, setScope] = useState<string>(() => (property?.company_id ? String(property.company_id) : "all"));
  const parsed = scope === "unassigned" ? { companyId: null, unassigned: true } : scope === "all" ? { companyId: null, unassigned: false } : { companyId: Number(scope), unassigned: false };
  const { data, loading, error, retry } = useLoad(() => fetchPortfolio(parsed, days), [scope, days]);

  return (
    <div className="space-y-6">
      <label className="block text-sm">
        <span className="mr-2 text-muted">Portfolio</span>
        <select value={scope} onChange={(e) => setScope(e.target.value)} className="rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm">
          <option value="all">All properties</option>
          {companies.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
          <option value="unassigned">Unassigned properties</option>
        </select>
      </label>

      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{ when: data !== null && data.scope.properties === 0, title: "No properties in this portfolio", body: "Assign properties to the company to compare them here." }}
      >
        {data && (
          <>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              {AVERAGES.map(([k, label]) => {
                const a = data.averages[k];
                return (
                  <div key={k} className="rounded-2xl border border-line bg-surface p-5">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm text-muted">Average {label}</p>
                      {a.value !== null && <DataLabelBadge label={a.label} />}
                    </div>
                    <p className="mt-1 text-3xl font-semibold tracking-tight">{fmtRate(a.value)}</p>
                    <p className="text-xs text-muted">{a.value !== null ? `across ${a.properties} properties` : a.note}</p>
                  </div>
                );
              })}
            </div>
            <p className="text-xs text-muted">{data.note}</p>

            <Panel title="Properties" label="MEASURED" subtitle={`${data.scope.properties} active propert${data.scope.properties === 1 ? "y" : "ies"}, ${data.window.start} to ${data.window.end}`}>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead className="text-left text-xs text-muted">
                    <tr className="border-b border-line">
                      <th className="py-2 pr-3 font-normal">Property</th>
                      <th className="w-56 py-2 pr-3 font-normal">AI Visibility</th>
                      <th className="py-2 pr-3 text-right font-normal">Citation Rate</th>
                      <th className="py-2 pr-3 text-right font-normal">Share of Voice</th>
                      <th className="py-2 text-right font-normal">Answers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.properties.map((r) => (
                      <tr key={r.property_id} className="border-b border-line/60">
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
            </Panel>

            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Shared content gaps" label={data.shared_gaps.length ? "MODELED" : undefined} subtitle="Topics where two or more properties have an open AI content gap.">
                {data.shared_gaps.length === 0 ? (
                  <p className="text-sm text-muted">No topic is a gap for more than one property.</p>
                ) : (
                  <ul className="space-y-1.5 text-sm">
                    {data.shared_gaps.map((g) => (
                      <li key={g.topic_key}>{g.text}</li>
                    ))}
                  </ul>
                )}
              </Panel>
              <Panel title="Sources AI cites across the portfolio" label={data.top_sources.length ? "OBSERVED" : undefined}>
                {data.top_sources.length === 0 ? (
                  <p className="text-sm text-muted">No citations in this window.</p>
                ) : (
                  <ul className="space-y-1.5 text-sm">
                    {data.top_sources.map((s) => (
                      <li key={s.domain} className="flex justify-between gap-2">
                        <span className="truncate">{s.domain}</span>
                        <span className="shrink-0 text-xs text-muted">
                          {s.citations} citations · {s.properties} propert{s.properties === 1 ? "y" : "ies"}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>
          </>
        )}
      </LoadState>
    </div>
  );
}
