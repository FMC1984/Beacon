"use client";

import { useState } from "react";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { DataLabelBadge, LoadState, NeedsProperty, Panel, useLoad } from "@/components/observatory/ui";
import { asUtc, fetchCitations } from "@/lib/observatory";
import { fmtDateTime } from "@/lib/format";

const PAGE = 50;

export default function CitationsPage() {
  const { propertyId, days } = useObservatory();
  const [domain, setDomain] = useState("");
  const [applied, setApplied] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, error, loading, retry } = useLoad(
    propertyId === null ? null : () => fetchCitations(propertyId, days, { domain: applied || undefined, offset, limit: PAGE }),
    [propertyId, days, applied, offset]
  );
  if (propertyId === null) return <NeedsProperty />;

  return (
    <Panel
      title="Citations"
      label="OBSERVED"
      subtitle="Every URL an AI answer cited in the responses scored for this property, as the provider reported it (or found in the answer text when the provider reports none)."
      actions={
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setOffset(0);
            setApplied(domain.trim().toLowerCase());
          }}
          className="flex gap-2"
        >
          <input
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            placeholder="Filter by domain"
            aria-label="Filter by domain"
            className="w-44 rounded-xl border border-line bg-surface-raised px-3 py-1.5 text-sm"
          />
          <button className="rounded-xl border border-line px-3 py-1.5 text-sm hover:bg-surface-raised">Apply</button>
        </form>
      }
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{
          when: data !== null && data.total === 0,
          title: applied ? `No citations from ${applied}` : "No citations in this window",
          body: "Citations appear once monitored AI answers cite web sources.",
        }}
      >
        {data && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 pr-3 font-normal">Source</th>
                    <th className="py-2 pr-3 font-normal">Type</th>
                    <th className="py-2 pr-3 font-normal">Platform</th>
                    <th className="py-2 pr-3 font-normal">Captured by</th>
                    <th className="py-2 font-normal">Observed</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((c) => (
                    <tr key={c.citation_id} className="border-b border-line/60 align-top">
                      <td className="max-w-md py-2 pr-3">
                        <a href={c.url} target="_blank" rel="noreferrer" className="block truncate text-violet-a hover:underline">
                          {c.title || c.url}
                        </a>
                        <span className="text-xs text-muted">
                          {c.domain}
                          {c.owned && <span className="ml-2 rounded-full bg-emerald-a/15 px-1.5 py-0.5 text-[10px] text-emerald-a">owned</span>}
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-xs text-muted">{(c.source_type ?? "other").replace(/_/g, " ")}</td>
                      <td className="py-2 pr-3 text-xs text-muted">{c.platform}</td>
                      <td className="py-2 pr-3 text-xs text-muted">
                        {c.capture_method === "prose_regex" ? "answer text" : c.capture_method.replace(/_/g, " ")}
                      </td>
                      <td className="py-2 text-xs text-muted">{fmtDateTime(asUtc(c.observed_at))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-muted">
              <span>
                {offset + 1} to {Math.min(offset + PAGE, data.total)} of {data.total} <DataLabelBadge label="OBSERVED" />
              </span>
              <span className="flex gap-2">
                <button
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE))}
                  className="rounded-lg border border-line px-2.5 py-1 disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  disabled={offset + PAGE >= data.total}
                  onClick={() => setOffset(offset + PAGE)}
                  className="rounded-lg border border-line px-2.5 py-1 disabled:opacity-40"
                >
                  Next
                </button>
              </span>
            </div>
          </>
        )}
      </LoadState>
    </Panel>
  );
}
