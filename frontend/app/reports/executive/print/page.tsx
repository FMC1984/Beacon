"use client";

/** Print-friendly executive report (Phase 16C). A standalone layout that
 * fetches its own data from URL params and auto-opens the print dialog, so
 * "Save as PDF" produces a real document, not a screenshot of the app. The
 * app sidebar is hidden in print via globals.css @media print rules. */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import {
  fetchExecutiveReport,
  type ExecCard,
  type ExecutiveReport as ExecReportData,
} from "@/lib/reports";
import { STATE_META } from "@/components/reports/DataStates";

function cardValue(c: ExecCard): string {
  if (c.state !== "complete" || c.value === null) {
    return STATE_META[c.state]?.label ?? c.state;
  }
  if (c.unit === "pct") return fmtPct(c.value);
  if (c.key === "content_score") return String(c.value);
  return fmtNum(c.value);
}

function PrintBody() {
  const params = useSearchParams();
  const propertyId = params.get("property_id");
  const days = Number(params.get("days") ?? "30");
  const compare = params.get("compare") === "true";
  const [data, setData] = useState<ExecReportData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchExecutiveReport(propertyId ? Number(propertyId) : null, days, compare)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [propertyId, days, compare]);

  // Print once the content has rendered.
  useEffect(() => {
    if (data && !("scope_required" in data && data.scope_required)) {
      const t = setTimeout(() => window.print(), 400);
      return () => clearTimeout(t);
    }
  }, [data]);

  if (error) return <p style={{ padding: 24 }}>Could not load report: {error}</p>;
  if (!data) return <p style={{ padding: 24 }}>Preparing report...</p>;
  if (data.scope_required) return <p style={{ padding: 24 }}>{data.message}</p>;

  return (
    <div className="print-doc">
      <header className="print-header">
        <div>
          <p className="print-brand">Beacon</p>
          <h1>Executive Report</h1>
        </div>
        <div className="print-meta">
          <p>{data.property_name}</p>
          <p>
            {fmtDate(data.window.start)} to {fmtDate(data.window.end)}
          </p>
          <p>Generated {fmtDate(data.generated_on)}</p>
        </div>
      </header>

      <section>
        <h2>Summary</h2>
        <ul className="print-narrative">
          {data.narrative.map((item, i) => (
            <li key={i}>
              {item.text}
              {item.evidence.length > 0 && (
                <span className="print-evidence"> Evidence: {item.evidence.join("; ")}.</span>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Key metrics</h2>
        <table className="print-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Value</th>
              <th>Source</th>
              <th>Through</th>
            </tr>
          </thead>
          <tbody>
            {data.cards.map((c) => (
              <tr key={c.key}>
                <td>{c.label}</td>
                <td>{cardValue(c)}</td>
                <td>{c.source}</td>
                <td>{c.last_data_date ? fmtDate(c.last_data_date) : "n/a"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Top actions</h2>
        {data.top_actions.length === 0 ? (
          <p>No actionable recommendations yet.</p>
        ) : (
          <ol className="print-actions">
            {data.top_actions.map((a, i) => (
              <li key={i}>
                <strong>{a.title}</strong>
                {a.explanation && <span> {a.explanation}</span>}
                <span className="print-evidence">
                  {" "}
                  Impact {a.impact ?? "n/a"}, effort {a.effort ?? "n/a"},{" "}
                  {a.supporting_signal_count} supporting signal
                  {a.supporting_signal_count === 1 ? "" : "s"}.
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="print-methodology">
        <h2>Methodology and notes</h2>
        <p>
          Figures are composed from Beacon&apos;s ingested data. Organic metrics
          come from Search Console and GA4 (organic medium). AI referral metrics
          reflect only sessions that passed referrer data; actual AI-influenced
          traffic is likely higher. AI mention rate is measured only above the
          minimum tested-query sample. Observed changes may be influenced by
          seasonality, competition, demand, and tracking changes, and are not
          claimed to be caused by any single action.
        </p>
        {compare && (
          <p>
            Comparison period: {fmtDate(data.previous_window.start)} to{" "}
            {fmtDate(data.previous_window.end)}. Metrics are compared only when
            both periods have compatible source coverage.
          </p>
        )}
      </section>

      <footer className="print-footer">
        Beacon Executive Report · {data.property_name} · Generated{" "}
        {fmtDate(data.generated_on)}
      </footer>
    </div>
  );
}

export default function ExecutivePrintPage() {
  return (
    <Suspense fallback={<p style={{ padding: 24 }}>Preparing report...</p>}>
      <PrintBody />
    </Suspense>
  );
}
