"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, Company, Property, fetchCompanies, fetchProperties } from "@/lib/api";
import { ScopeSelect } from "@/components/ScopeSelect";

type Opportunity = {
  source: string;
  source_label: string;
  title: string;
  reason: string;
  state: string;
  impact: string | null;
  effort: string | null;
  gate_reason: string | null;
  corroborating_sources: string[];
  priority: number;
};

type Analysis = {
  property_name: string;
  total: number;
  by_source: Record<string, number>;
  opportunities: Opportunity[];
  suppressed: Opportunity[];
  insufficient: Opportunity[];
  summary: string;
};

const STATE_CHIP: Record<string, string> = {
  Actionable: "bg-emerald-a/15 text-emerald-a",
  Monitor: "bg-cyan-a/15 text-cyan-a",
  "Requires confirmation": "bg-amber-a/15 text-amber-a",
  Suppressed: "bg-pink-a/15 text-pink-a",
  "Insufficient data": "bg-line/60 text-muted",
};

const SOURCE_CHIP = "bg-violet-a/15 text-violet-a";

function OppCard({ o }: { o: Opportunity }) {
  return (
    <div className="rounded-xl border border-line bg-surface-raised p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${SOURCE_CHIP}`}>
          {o.source_label}
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
            STATE_CHIP[o.state] ?? "bg-line/60 text-muted"
          }`}
        >
          {o.state}
        </span>
        {o.impact && (
          <span className="text-[11px] text-muted">
            {o.impact} impact{o.effort ? ` · ${o.effort} effort` : ""}
          </span>
        )}
        {o.corroborating_sources.length > 0 && (
          <span
            className="rounded-full bg-cyan-a/10 px-2 py-0.5 text-[11px] text-cyan-a"
            title={`Also flagged by ${o.corroborating_sources.join(", ")}`}
          >
            +{o.corroborating_sources.length} signal
            {o.corroborating_sources.length === 1 ? "" : "s"}
          </span>
        )}
        <span className="font-medium">{o.title}</span>
      </div>
      <p className="mt-1.5 text-sm text-muted">{o.reason}</p>
      {o.gate_reason && <p className="mt-1 text-xs text-amber-a">{o.gate_reason}</p>}
    </div>
  );
}

export default function OpportunitiesPage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [data, setData] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchProperties()
      .then((p) => {
        setProperties(p);
        if (p.length) setPropertyId(p[0].id);
      })
      .catch(() => setError("Could not reach the Beacon API."));
    fetchCompanies().then(setCompanies).catch(() => {});
  }, []);

  const load = useCallback((id: number) => {
    fetch(`${API_BASE}/opportunities/${id}`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setError("Could not reach the Beacon API."));
  }, []);

  useEffect(() => {
    if (propertyId !== null) load(propertyId);
  }, [propertyId, load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Opportunities</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            One prioritized to-do list, unified across Content IQ, Review IQ, AI
            Query Signals, AI Visibility, and Competitor IQ. Context-gated;
            suppressed and not-enough-data items are shown honestly, not hidden.
          </p>
        </div>
        <ScopeSelect
          companies={companies}
          properties={properties}
          value={propertyId}
          onChange={setPropertyId}
        />
      </div>

      {error && (
        <div className="rounded-2xl border border-pink-a/40 bg-pink-a/10 p-3 text-sm text-pink-a">
          {error}
        </div>
      )}

      {data && (
        <>
          <div className="rounded-2xl border border-line bg-surface px-4 py-3 text-sm text-muted">
            {data.summary}
          </div>

          {/* Prioritized actionable list */}
          {data.opportunities.length === 0 ? (
            <div className="rounded-2xl border border-line bg-surface p-8 text-center text-sm text-muted">
              No actionable opportunities right now.
            </div>
          ) : (
            <section className="space-y-2">
              <h2 className="text-sm font-medium text-muted">
                Prioritized ({data.opportunities.length})
              </h2>
              {data.opportunities.map((o) => (
                <div key={`${o.source}-${o.priority}`} className="flex gap-3">
                  <span className="mt-4 w-6 shrink-0 text-right text-sm font-semibold text-muted">
                    {o.priority}
                  </span>
                  <div className="flex-1">
                    <OppCard o={o} />
                  </div>
                </div>
              ))}
            </section>
          )}

          {/* Requires confirmation / suppressed */}
          {data.suppressed.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm font-medium text-muted">
                Blocked by property context ({data.suppressed.length})
              </h2>
              <p className="text-xs text-muted">
                These would touch restricted positioning or fair-housing-sensitive
                framing for this property, so Beacon is not recommending them.
              </p>
              {data.suppressed.map((o, i) => (
                <OppCard key={i} o={o} />
              ))}
            </section>
          )}

          {/* Insufficient data */}
          {data.insufficient.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm font-medium text-muted">
                Awaiting more data ({data.insufficient.length})
              </h2>
              {data.insufficient.map((o, i) => (
                <OppCard key={i} o={o} />
              ))}
            </section>
          )}

          {/* Source coverage */}
          <section className="rounded-2xl border border-line bg-surface p-5">
            <h2 className="mb-2 text-sm font-medium text-muted">Coverage by module</h2>
            <div className="flex flex-wrap gap-2 text-xs text-muted">
              {Object.entries(data.by_source).map(([label, n]) => (
                <span key={label} className="rounded-full border border-line px-2.5 py-1">
                  {label}: {n}
                </span>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
