"use client";

/** Audience geography report (Phase 16G). Where visitors come from, by city
 * and region, from GA4's City / Region dimensions. Sessions GA4 could not
 * place are shown honestly as "Unknown" and the located share is always
 * stated. When GA4 rows exist but none carry a city, the report asks for a
 * re-export rather than pretending nobody had a location. Every AI figure
 * carries the fixed undercount disclosure. */

import { useEffect, useState } from "react";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import {
  fetchAudienceReport,
  type AudienceCity,
  type AudienceRegion,
  type AudienceReport as AudienceReportData,
} from "@/lib/reports";
import { EmptyState, ErrorState } from "./DataStates";
import { ReportMetricCard } from "./ReportMetricCard";
import { useReportContext } from "./ReportContext";

type Loaded = Extract<AudienceReportData, { has_data: true }>;

function Section({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h3 className="text-sm font-medium">{title}</h3>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function cityLabel(city: string, region: string | null): string {
  return region ? `${city}, ${region}` : city;
}

function SummaryCards({ report }: { report: Loaded }) {
  const s = report.summary;
  const last = report.last_data_date;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <ReportMetricCard label="Total sessions" state="complete" value={fmtNum(s.total_sessions)} source="GA4" lastDataDate={last} />
      <ReportMetricCard
        label="Located share"
        state={report.geography_available ? "complete" : "empty"}
        value={s.located_share !== null ? fmtPct(s.located_share) : undefined}
        stateDetail="No sessions carry a city yet."
        source="GA4"
        lastDataDate={last}
        sample={{ numerator: s.located_sessions, denominator: s.total_sessions, unit: "sessions with a city" }}
      />
      <ReportMetricCard
        label="Cities represented"
        state={report.geography_available ? "complete" : "empty"}
        value={report.geography_available ? fmtNum(s.distinct_cities) : undefined}
        stateDetail="No sessions carry a city yet."
        source="GA4"
        lastDataDate={last}
      />
      <ReportMetricCard
        label="Top city"
        state={s.top_city ? "complete" : "empty"}
        value={s.top_city ? cityLabel(s.top_city.city, s.top_city.region) : undefined}
        stateDetail="No located sessions yet."
        source="GA4"
        lastDataDate={last}
      />
    </div>
  );
}

function ShareBar({ share, isUnknown }: { share: number | null; isUnknown?: boolean }) {
  const pct = share !== null ? Math.round(share * 100) : 0;
  return (
    <div className="h-4 w-full rounded bg-surface-raised">
      <div
        className={`h-4 rounded ${isUnknown ? "bg-muted/40" : "bg-violet-a/70"}`}
        style={{ width: `${pct}%` }}
        role="img"
        aria-label={share !== null ? `${pct} percent of sessions` : "no share"}
      />
    </div>
  );
}

function CityTable({ report }: { report: Loaded }) {
  if (report.cities.length === 0) {
    return <EmptyState title="No sessions in range" body="There are no GA4 sessions in the selected window." />;
  }
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="py-2 pr-3 font-medium">City</th>
              <th className="px-2 py-2 font-medium">Region</th>
              <th className="px-2 py-2 text-right font-medium">Sessions</th>
              <th className="px-2 py-2 font-medium">Share</th>
              <th className="px-2 py-2 text-right font-medium">Engaged</th>
              <th className="px-2 py-2 text-right font-medium">AI</th>
            </tr>
          </thead>
          <tbody>
            {report.cities.map((c: AudienceCity, i) => {
              const unknown = c.city === "Unknown";
              return (
                <tr key={`${c.city}-${c.region ?? ""}-${i}`} className="border-t border-line/50">
                  <td className={`py-2 pr-3 ${unknown ? "text-muted" : "font-medium"}`}>{c.city}</td>
                  <td className="px-2 py-2 text-muted">{c.region ?? "—"}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{fmtNum(c.sessions)}</td>
                  <td className="px-2 py-2">
                    <div className="flex items-center gap-2">
                      <ShareBar share={c.sessions_share} isUnknown={unknown} />
                      <span className="w-12 shrink-0 text-right text-xs text-muted tabular-nums">
                        {c.sessions_share !== null ? fmtPct(c.sessions_share) : ""}
                      </span>
                    </div>
                  </td>
                  <td className="px-2 py-2 text-right text-muted tabular-nums">
                    {c.engagement_rate !== null ? fmtPct(c.engagement_rate) : "—"}
                  </td>
                  <td className="px-2 py-2 text-right text-muted tabular-nums">
                    {c.ai_sessions > 0 ? fmtNum(c.ai_sessions) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {report.cities_total > report.cities_shown && (
        <p className="mt-3 text-xs text-muted">
          Showing the top {report.cities_shown} of {fmtNum(report.cities_total)} locations. The CSV export carries the full list.
        </p>
      )}
    </div>
  );
}

function RegionList({ regions }: { regions: AudienceRegion[] }) {
  if (regions.length === 0) {
    return <EmptyState title="No region data" body="No sessions in range carry a region. Add the Region dimension to your GA4 export to see this." />;
  }
  const max = Math.max(...regions.map((r) => r.sessions), 1);
  return (
    <ul className="space-y-2">
      {regions.slice(0, 15).map((r) => (
        <li key={r.region} className="flex items-center gap-3 text-sm">
          <span className="w-40 shrink-0 truncate" title={r.region}>{r.region}</span>
          <div className="h-5 flex-1 rounded bg-surface-raised">
            <div
              className="h-5 rounded bg-cyan-a/60"
              style={{ width: `${(r.sessions / max) * 100}%` }}
              role="img"
              aria-label={`${r.region}: ${r.sessions} sessions`}
            />
          </div>
          <span className="w-14 text-right tabular-nums">{fmtNum(r.sessions)}</span>
          <span className="w-14 text-right text-xs text-muted tabular-nums">
            {r.sessions_share !== null ? fmtPct(r.sessions_share) : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function AudienceReport() {
  const { scope, days } = useReportContext();
  const [data, setData] = useState<AudienceReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchAudienceReport(scope, days)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.propertyId, scope.companyId, scope.unassigned, days, attempt]);

  if (error) return <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />;
  if (!data) return <p className="text-sm text-muted">Loading audience report...</p>;

  if (!data.has_data) {
    return <EmptyState title="No traffic data yet" body={data.message} />;
  }

  return (
    <div className="space-y-6">
      <p className="text-xs text-muted">
        {data.scope_label} · {fmtDate(data.window.start)} to {fmtDate(data.window.end)}
        {data.window.anchored_to_latest_data && " · anchored to latest GA4 data"}
      </p>

      {!data.geography_available && data.geography_message && (
        <div className="rounded-2xl border border-amber-a/40 bg-amber-a/10 p-5">
          <h3 className="text-sm font-medium text-amber-a">No location data in this traffic</h3>
          <p className="mt-2 text-sm text-muted">{data.geography_message}</p>
        </div>
      )}

      <SummaryCards report={data} />

      <Section
        title="Where visitors are"
        sub="Sessions by city, from GA4's approximate geolocation. Sessions GA4 could not place are grouped under Unknown."
      >
        <CityTable report={data} />
      </Section>

      <Section title="By region" sub="Sessions grouped by GA4 region (state or province). Sessions without a region are omitted from this rollup.">
        <RegionList regions={data.regions} />
      </Section>

      <div className="space-y-1 text-xs text-muted">
        <p>{data.geography_note}</p>
        <p>{data.disclosure}</p>
      </div>
    </div>
  );
}
