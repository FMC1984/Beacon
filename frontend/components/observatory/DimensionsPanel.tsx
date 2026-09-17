"use client";

/** AI Visibility by area and by audience: the property's cluster rollups
 * grouped by the cluster's neighborhood (geography) and persona. Both
 * dimensions are operator-asserted (a neighborhood on the property, an
 * audience from Property Context or attributes); Beacon never infers them. */

import Link from "next/link";
import { fetchDimensions, fmtRate, type DimensionRow } from "@/lib/observatory";
import { LoadState, Panel, ShareBar, useLoad } from "./ui";

function Rows({ rows, empty }: { rows: DimensionRow[]; empty: string }) {
  if (rows.length === 0) return <p className="text-xs text-muted">{empty}</p>;
  return (
    <table className="w-full text-sm">
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className="border-b border-line/60">
            <td className="py-1.5 pr-3">
              <span className="block">{r.label}</span>
              <span className="text-[11px] text-muted">{r.clusters} question{r.clusters === 1 ? "" : "s"} · {r.answers} answers</span>
            </td>
            <td className="w-44 py-1.5">
              {r.ai_visibility.value !== null ? (
                <div className="flex items-center gap-2">
                  <ShareBar value={r.ai_visibility.value} />
                  <span className="w-10 shrink-0 text-right text-xs">{fmtRate(r.ai_visibility.value)}</span>
                </div>
              ) : (
                <span className="text-xs text-muted">below sample ({r.answers} of {r.ai_visibility.minimum_sample})</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function DimensionsPanel({ propertyId, days }: { propertyId: number; days: number }) {
  const { data, error, loading, retry } = useLoad(() => fetchDimensions(propertyId, days), [propertyId, days]);
  return (
    <Panel
      title="Visibility by area and audience"
      label="MEASURED"
      subtitle="AI Visibility across the neighborhood questions and the audience-specific questions this property is monitored on. Both come from what you told Beacon, never from a guess."
    >
      <LoadState loading={loading && !data} error={error} retry={retry}>
        {data && (
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">By area</h3>
              <Rows
                rows={data.regions}
                empty={
                  data.property_geography
                    ? "No neighborhood answers in this window yet."
                    : "Set a neighborhood on the property to monitor its area questions."
                }
              />
            </div>
            <div>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">By audience</h3>
              <Rows
                rows={data.personas}
                empty={
                  data.property_personas.length
                    ? "No audience answers in this window yet."
                    : "Set the property type on Property Context (senior, student, luxury, affordable) to monitor an audience's questions."
                }
              />
            </div>
          </div>
        )}
      </LoadState>
      {data && (
        <p className="mt-3 text-xs text-muted">
          {data.note}{" "}
          <Link href={`/properties?property_id=${propertyId}`} className="text-violet-a hover:underline">
            Edit the property ›
          </Link>
        </p>
      )}
    </Panel>
  );
}
