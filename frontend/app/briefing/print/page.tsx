"use client";

/** Print-friendly Monthly Strategic Briefing (Phase 17E). Same pattern as the
 * executive report's print route (16C): a standalone black-on-white document
 * that auto-opens the print dialog, so "Save as PDF" produces a real client
 * deliverable rather than a screenshot of the dark UI. Reuses the .print-doc
 * styles from globals.css. */

import { Suspense, useEffect, useState } from "react";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import {
  fetchBriefing,
  type Briefing,
  type BriefingKpi,
  type BriefingResponse,
} from "@/lib/briefing";

function kpiValue(k: BriefingKpi): string {
  if (k.value === null) return "n/a";
  if (k.unit === "pct") return fmtPct(k.value);
  if (k.key === "content_score") return String(k.value);
  return fmtNum(k.value);
}

function PrintBody() {
  const [data, setData] = useState<BriefingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // window.location avoids the Suspense boundary useSearchParams requires.
    const params = new URLSearchParams(window.location.search);
    const pid = params.get("property_id");
    const year = params.get("year");
    const month = params.get("month");
    if (!pid) {
      setError("Missing property.");
      return;
    }
    fetchBriefing(
      Number(pid),
      year ? Number(year) : undefined,
      month ? Number(month) : undefined
    )
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (data && !data.scope_required) {
      const t = setTimeout(() => window.print(), 400);
      return () => clearTimeout(t);
    }
  }, [data]);

  if (error) return <p style={{ padding: 24 }}>Could not load briefing: {error}</p>;
  if (!data) return <p style={{ padding: 24 }}>Preparing briefing...</p>;
  if (data.scope_required) return <p style={{ padding: 24 }}>{data.message}</p>;
  const b: Briefing = data;

  return (
    <div className="print-doc">
      <header className="print-header">
        <div>
          <p className="print-brand">Beacon</p>
          <h1>Monthly Strategic Briefing</h1>
        </div>
        <div className="print-meta">
          <p>{b.property_name}</p>
          <p>{b.period.label} (vs {b.comparison_period.label})</p>
          <p>Generated {fmtDate(b.generated_on)}</p>
        </div>
      </header>

      <section>
        <h2>Property health</h2>
        <p className="print-evidence">{b.health.summary}</p>
        <table className="print-table">
          <thead>
            <tr><th>Module</th><th>Status</th><th>Why</th></tr>
          </thead>
          <tbody>
            {b.health.modules.map((m) => (
              <tr key={m.key}>
                <td>{m.label}</td>
                <td>{m.status_label}</td>
                <td>{m.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Executive summary</h2>
        {b.executive_summary.length === 0 ? (
          <p>Not enough connected data to summarize this month.</p>
        ) : (
          <ul className="print-narrative">
            {b.executive_summary.map((item, i) => (
              <li key={i}>
                {item.text}
                {item.evidence.length > 0 && (
                  <span className="print-evidence"> Evidence: {item.evidence.join("; ")}.</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2>Key metrics</h2>
        <table className="print-table">
          <thead>
            <tr><th>Metric</th><th>Value</th><th>Prior month</th></tr>
          </thead>
          <tbody>
            {b.kpis.map((k) => (
              <tr key={k.key}>
                <td>{k.label}</td>
                <td>{kpiValue(k)}</td>
                <td>
                  {k.comparison && k.comparison.previous !== null
                    ? (k.unit === "pct" ? fmtPct(k.comparison.previous) : fmtNum(k.comparison.previous))
                    : "n/a"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {b.story && (b.story.wins.length > 0 || b.story.risks.length > 0 || b.story.trends.length > 0) && (
        <section>
          <h2>This month&apos;s story</h2>
          {(["wins", "risks", "trends"] as const).map((g) =>
            b.story![g].length > 0 ? (
              <div key={g}>
                <p><strong>{g === "trends" ? "Worth watching" : g[0].toUpperCase() + g.slice(1)}</strong></p>
                <ul className="print-narrative">
                  {b.story![g].map((item, i) => (
                    <li key={i}>
                      {item.text}
                      <span className="print-evidence"> {item.evidence.join("; ")}.</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null
          )}
          <p className="print-evidence">{b.story.note}</p>
        </section>
      )}

      {b.cross_system && b.cross_system.insights.length > 0 && (
        <section>
          <h2>Cross-system insights</h2>
          <ul className="print-narrative">
            {b.cross_system.insights.map((ins, i) => (
              <li key={i}>
                <strong>{ins.title}.</strong>{" "}
                {ins.observations.map((o) => o.text).join(" ")}
                <span className="print-evidence"> {ins.framing}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2>Top priorities</h2>
        {b.top_priorities.length === 0 ? (
          <p>No prioritized actions this month.</p>
        ) : (
          <ol className="print-actions">
            {b.top_priorities.map((a, i) => (
              <li key={i}>
                <strong>{a.title}</strong>
                {a.explanation && <span> {a.explanation}</span>}
                <span className="print-evidence">
                  {" "}Impact {a.impact ?? "n/a"}, effort {a.effort ?? "n/a"},{" "}
                  {a.supporting_signal_count} supporting signal{a.supporting_signal_count === 1 ? "" : "s"}.
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>

      {b.strategic_questions && b.strategic_questions.length > 0 && (
        <section>
          <h2>Questions worth investigating</h2>
          <ul className="print-narrative">
            {b.strategic_questions.map((q, i) => (
              <li key={i}>
                {q.text}
                <span className="print-evidence"> {q.why}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="print-methodology">
        <h2>Methodology and notes</h2>
        <p>
          Composed from Beacon&apos;s ingested data for {b.period.label}, compared
          with {b.comparison_period.label}. Module health statuses follow fixed,
          explainable rules; overall health is a count of healthy modules, not a
          combined score. Story items and insights are observed movements from
          stored data; co-occurrence is not causation. Missing or unconnected
          sources are reported as such, never as zero.
        </p>
      </section>

      <footer className="print-footer">
        Beacon Monthly Strategic Briefing · {b.property_name} · {b.period.label} ·
        Generated {fmtDate(b.generated_on)}
      </footer>
    </div>
  );
}

export default function BriefingPrintPage() {
  return (
    <Suspense fallback={<p style={{ padding: 24 }}>Preparing briefing...</p>}>
      <PrintBody />
    </Suspense>
  );
}
