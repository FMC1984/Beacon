"use client";

import Link from "next/link";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { FormulaNote, LoadState, NeedsProperty, Panel, ShareBar, useLoad } from "@/components/observatory/ui";
import { fetchSources, fmtRate } from "@/lib/observatory";

export default function SourcesPage() {
  const { propertyId, days, withScope } = useObservatory();
  const { data, error, loading, retry } = useLoad(
    propertyId === null ? null : () => fetchSources(propertyId, days, 100),
    [propertyId, days]
  );
  if (propertyId === null) return <NeedsProperty />;

  return (
    <Panel
      title="Source influence"
      label="MEASURED"
      subtitle="Which domains AI answers lean on when they answer questions this property is scored for. A market answer counts for every property it scored."
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{ when: data !== null && data.total_citations === 0, title: "No cited sources yet", body: "Sources appear once monitored AI answers cite the web." }}
      >
        {data && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 pr-3 font-normal">Domain</th>
                    <th className="py-2 pr-3 font-normal">Type</th>
                    <th className="py-2 pr-3 text-right font-normal">Citations</th>
                    <th className="py-2 pr-3 text-right font-normal">Responses</th>
                    <th className="w-48 py-2 font-normal">Share of citations</th>
                  </tr>
                </thead>
                <tbody>
                  {data.domains.map((d) => (
                    <tr key={`${d.domain}-${d.source_type}`} className="border-b border-line/60">
                      <td className="py-2 pr-3">
                        <Link
                          href={`${withScope("/ai-visibility/citations")}`}
                          className="hover:text-violet-a"
                          title="Open the citations list"
                        >
                          {d.domain}
                        </Link>
                      </td>
                      <td className="py-2 pr-3 text-xs text-muted">{(d.source_type ?? "other").replace(/_/g, " ")}</td>
                      <td className="py-2 pr-3 text-right">{d.citations}</td>
                      <td className="py-2 pr-3 text-right text-muted">{d.responses}</td>
                      <td className="py-2">
                        <div className="flex items-center gap-2">
                          <ShareBar value={d.share} tone="cyan" />
                          <span className="w-10 shrink-0 text-right text-xs text-muted">{fmtRate(d.share)}</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <FormulaNote formula={data.formula} />
          </>
        )}
      </LoadState>
    </Panel>
  );
}
