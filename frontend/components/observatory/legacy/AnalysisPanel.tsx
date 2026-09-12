"use client";

/** Pre-Observatory property analysis (score, platform mention rate, source
 * landscape, fact checks, recommendations), moved verbatim. LegacyAnalysis
 * loads it for a property. */

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import { type Analysis, REC_CHIP, pct } from "./shared";

export type AnalysisSection = "score" | "platform" | "sources" | "facts" | "recommendations" | "deferred";

export function AnalysisPanel({ a, only }: { a: Analysis | null; only?: AnalysisSection[] }) {
  const show = (k: AnalysisSection) => !only || only.includes(k);
  if (!a) return <p className="text-muted">Loading…</p>;
  if (!a.has_queries) {
    return (
      <div className="rounded-2xl border border-line bg-surface p-10 text-center">
        <p className="text-lg font-medium">No analysis yet</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted">
          Run some queries under the &quot;Run &amp; Queries&quot; tab. Beacon
          needs at least {a.sample?.minimum ?? 3} to characterize visibility.
        </p>
      </div>
    );
  }
  const insufficient = a.sample && !a.sample.sufficient;
  return (
    <div className="space-y-4">
      {/* Score / sample */}
      {show("score") && (
      <section className="rounded-2xl border border-line bg-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-medium text-muted">AI Visibility score</h2>
            {a.score ? (
              <p className="mt-1 text-3xl font-semibold">
                {a.score.value}
                <span className="ml-2 text-base font-normal text-muted">
                  {a.score.grade} · directional
                </span>
              </p>
            ) : (
              <p className="mt-1 text-lg font-medium text-amber-a">
                Not enough data to score
              </p>
            )}
          </div>
          <p className="text-xs text-muted">
            {a.sample?.total_queries} quer
            {a.sample?.total_queries === 1 ? "y" : "ies"}
            {a.date_range ? ` · ${a.date_range.start} to ${a.date_range.end}` : ""}
          </p>
        </div>
        {insufficient && (
          <p className="mt-2 rounded-lg bg-amber-a/10 px-3 py-2 text-xs text-amber-a">
            Sample is below the {a.sample?.minimum}-query minimum. Everything below
            is anecdotal, not a measurement.
          </p>
        )}
        {a.score && (
          <div className="mt-3 space-y-1">
            {a.score.breakdown.map((b) => (
              <p key={b.component} className="text-xs text-muted">
                <span className="font-medium text-foreground">
                  {b.component.replace(/_/g, " ")}
                </span>{" "}
                {b.score} (weight {b.weight}): {b.explanation}
              </p>
            ))}
          </div>
        )}
      </section>
      )}

      {/* Mention by platform */}
      {show("platform") && (
      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="mb-3 text-sm font-medium text-muted">Mention rate by platform</h2>
        <div className="space-y-2">
          {(a.by_platform ?? []).map((p) => (
            <div key={p.label} className="flex items-center justify-between text-sm">
              <span>{p.label}</span>
              <span className="text-muted">
                {p.mention_rate_status === "measured"
                  ? `${p.mentions}/${p.queries} mentioned (${pct(p.mention_rate ?? 0)})`
                  : `${p.mentions}/${p.queries} mentioned (insufficient sample)`}
              </span>
            </div>
          ))}
        </div>
      </section>
      )}

      {/* Source landscape + own site */}
      {show("sources") && (
      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="mb-1 text-sm font-medium text-muted">Source landscape</h2>
        <p className="mb-3 text-xs text-muted">
          Which sources the AI leans on (not cross-referenced against Google
          rankings; that is deferred).
        </p>
        {a.own_site && (
          <p
            className={`mb-3 text-xs ${
              a.own_site.status === "cited"
                ? "text-emerald-a"
                : a.own_site.status === "not_cited"
                ? "text-amber-a"
                : "text-muted"
            }`}
          >
            {a.own_site.explanation}
          </p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {(a.source_landscape ?? []).map((s) => (
            <span
              key={s.domain}
              className="rounded-full border border-line px-2.5 py-1 text-[11px] text-muted"
            >
              {s.domain} · {s.cited_in_queries}
            </span>
          ))}
          {(a.source_landscape ?? []).length === 0 && (
            <span className="text-xs text-muted">No sources cited in any response.</span>
          )}
        </div>
      </section>
      )}

      {/* Fact-check findings */}
      {show("facts") && a.fact_checks && (a.fact_checks.contradictions.length > 0 || a.fact_checks.cannot_verify_count > 0) && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-3 text-sm font-medium text-muted">Fact-check findings</h2>
          {a.fact_checks.contradictions.map((c, i) => (
            <div key={i} className="mb-2 rounded-lg border border-amber-a/30 bg-amber-a/5 p-3 text-xs">
              <span className="font-medium text-amber-a">
                Contradiction: {c.field.replace(/_/g, " ")}
              </span>
              <p className="mt-0.5 text-muted">
                Known {c.field.replace(/_/g, " ")}: {c.known_value}. {c.evidence}
              </p>
            </div>
          ))}
          {a.fact_checks.cannot_verify_count > 0 && (
            <p className="text-xs text-muted">
              Property type could not be verified for {a.fact_checks.cannot_verify_count}{" "}
              response(s) (Property Context not set; reported as &quot;cannot
              verify&quot;, not assumed correct).
            </p>
          )}
        </section>
      )}

      {/* Recommendations */}
      {show("recommendations") && (
      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="mb-3 text-sm font-medium text-muted">Recommendations</h2>
        {(a.recommendations ?? []).length === 0 ? (
          <p className="text-sm text-muted">
            No evidence-backed recommendations for this sample.
          </p>
        ) : (
          <div className="space-y-2">
            {a.recommendations!.map((r, i) => (
              <div key={i} className="rounded-xl border border-line bg-surface-raised p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      REC_CHIP[r.state] ?? "bg-line/60 text-muted"
                    }`}
                  >
                    {r.state}
                  </span>
                  <span className="font-medium">{r.title}</span>
                </div>
                <p className="mt-1.5 text-sm text-muted">{r.reason}</p>
                {r.gate_reason && (
                  <p className="mt-1 text-xs text-amber-a">{r.gate_reason}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
      )}

      {/* Deferred, stated honestly */}
      {show("deferred") && a.deferred && a.deferred.length > 0 && (
      <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-2 text-sm font-medium text-muted">
            Deliberately not measured yet
          </h2>
          <ul className="space-y-1 text-xs text-muted">
            {a.deferred.map((d, i) => (
              <li key={i}>• {d}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function LegacyAnalysis({ propertyId, only }: { propertyId: number | null; only?: AnalysisSection[] }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  useEffect(() => {
    if (propertyId === null) return;
    let cancelled = false;
    fetch(`${API_BASE}/ai-visibility/${propertyId}/analysis`)
      .then((r) => r.json())
      .then((a) => !cancelled && setAnalysis(a))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [propertyId]);
  return <AnalysisPanel a={analysis} only={only} />;
}
