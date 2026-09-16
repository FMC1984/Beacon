"use client";

/** Semantic Intelligence report. One row per topic in the shared taxonomy,
 * one column per source, so the disagreements between what a property says,
 * what residents say, what AI says and what people search are visible at a
 * glance. A source the property does not have is a labeled state, never an
 * empty cell implying silence. */

import { useEffect, useState } from "react";
import {
  fetchSemanticReport,
  type SemanticGap,
  type SemanticReport as SemanticReportData,
  type SemanticTopic,
} from "@/lib/reports";
import { EmptyState, ErrorState, StateBadge } from "./DataStates";
import { useReportContext } from "./ReportContext";

const COVERAGE_META: Record<SemanticTopic["coverage_state"], { label: string; cls: string }> = {
  covered: { label: "Covered", cls: "border-emerald-a/40 bg-emerald-a/10 text-emerald-a" },
  site_only: { label: "Site only", cls: "border-cyan-a/40 bg-cyan-a/10 text-cyan-a" },
  gap: { label: "Gap", cls: "border-amber-a/40 bg-amber-a/10 text-amber-a" },
  not_discussed: { label: "Not discussed", cls: "border-line bg-surface-raised text-muted" },
};

const GAP_META: Record<SemanticGap["type"], { label: string; cls: string }> = {
  demand_gap: { label: "Search demand", cls: "border-amber-a/40 bg-amber-a/10 text-amber-a" },
  content_gap: { label: "Content gap", cls: "border-violet-a/40 bg-violet-a/10 text-violet-a" },
  mismatch: { label: "Mismatch", cls: "border-pink-a/40 bg-pink-a/10 text-pink-a" },
  ai_gap: { label: "AI gap", cls: "border-cyan-a/40 bg-cyan-a/10 text-cyan-a" },
};

const LEAN_CLS: Record<string, string> = {
  positive: "text-emerald-a",
  negative: "text-pink-a",
  mixed: "text-amber-a",
};

function Cell({ on, children, title }: { on: boolean; children: React.ReactNode; title?: string }) {
  return (
    <td className={`px-3 py-2 text-xs ${on ? "" : "text-muted/50"}`} title={title}>
      {children}
    </td>
  );
}

export function SemanticReport() {
  const { propertyId } = useReportContext();
  const [data, setData] = useState<SemanticReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [openTopic, setOpenTopic] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // State is only set from the promise callbacks, so the effect never
    // triggers a synchronous cascading render.
    fetchSemanticReport(propertyId)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch(() => !cancelled && setError("Could not load the Semantic Intelligence report."));
    return () => {
      cancelled = true;
    };
  }, [propertyId, nonce]);

  if (error) return <ErrorState message={error} onRetry={() => setNonce((n) => n + 1)} />;
  if (!data) return <p className="text-sm text-muted">Loading...</p>;
  if (data.scope_required) {
    return <EmptyState title="Choose a property" body={data.message} />;
  }
  if (!data.has_data) {
    return (
      <EmptyState
        title="No sources to compare yet"
        body="This report compares site content, reviews, AI answers and Search Console. Import at least one of them for this property."
      />
    );
  }

  const discussed = data.topics.filter((t) => t.coverage_state !== "not_discussed");
  const quiet = data.topics.filter((t) => t.coverage_state === "not_discussed");

  return (
    <div className="space-y-6">
      <p className="text-xs text-muted">
        {data.property_name} · {data.window.start} to {data.window.end} · taxonomy {data.taxonomy_version}
      </p>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          ["Topics discussed", `${data.summary.topics_discussed} of ${data.summary.topics_total}`],
          ["Covered on the site", String(data.summary.topics_covered_on_site)],
          ["Sources compared", String(data.summary.sources_available)],
          ["Gaps found", String(data.summary.gaps)],
        ].map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-line bg-surface p-5">
            <p className="text-sm text-muted">{label}</p>
            <p className="mt-1 text-3xl font-semibold tracking-tight">{value}</p>
          </div>
        ))}
      </div>

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="mb-3 text-sm font-medium">Sources compared</h2>
        <ul className="grid gap-2 sm:grid-cols-2">
          {data.sources.map((s) => (
            <li key={s.key} className="flex items-start justify-between gap-3 rounded-xl bg-surface-raised p-3">
              <div>
                <p className="text-sm font-medium">{s.label}</p>
                <p className="text-xs text-muted">{s.note}</p>
              </div>
              <span className="flex shrink-0 items-center gap-2">
                <span className="text-xs text-muted">{s.documents}</span>
                <StateBadge state={s.state} />
              </span>
            </li>
          ))}
        </ul>
      </section>

      {data.gaps.length > 0 && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-1 text-sm font-medium">Where the sources disagree</h2>
          <p className="mb-3 text-xs text-muted">
            Each finding compares two sources this property actually has. Nothing is inferred from a source that is
            not connected.
          </p>
          <ul className="space-y-2">
            {data.gaps.map((g) => (
              <li key={`${g.type}-${g.topic}`} className="rounded-xl border border-line bg-surface-raised p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${GAP_META[g.type].cls}`}>
                    {GAP_META[g.type].label}
                  </span>
                  <span className="text-sm font-medium">{g.headline}</span>
                </div>
                <ul className="mt-1.5 list-inside list-disc text-xs text-muted">
                  {g.evidence.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="mb-1 text-sm font-medium">Topic coverage</h2>
        <p className="mb-3 text-xs text-muted">
          Click a topic for its matched evidence. Dimmed cells mean the source did not raise the topic.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr className="border-b border-line">
                <th className="px-3 py-2 font-normal">Topic</th>
                <th className="px-3 py-2 font-normal">Site content</th>
                <th className="px-3 py-2 font-normal">Reviews</th>
                <th className="px-3 py-2 font-normal">AI answers</th>
                <th className="px-3 py-2 font-normal">Search</th>
                <th className="px-3 py-2 font-normal">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {discussed.map((t) => (
                <tr
                  key={t.key}
                  onClick={() => setOpenTopic(openTopic === t.key ? null : t.key)}
                  className="cursor-pointer border-b border-line/60 hover:bg-surface-raised"
                >
                  <td className="px-3 py-2 font-medium">{t.label}</td>
                  <Cell on={t.content.present} title={t.content.matched_terms.join(", ")}>
                    {t.content.present ? t.content.pages.join(", ") : "not mentioned"}
                  </Cell>
                  <Cell on={t.reviews.present}>
                    {t.reviews.present ? (
                      <>
                        {t.reviews.mentions} mention{t.reviews.mentions === 1 ? "" : "s"}
                        {t.reviews.lean && (
                          <span className={`ml-1 ${LEAN_CLS[t.reviews.lean]}`}>· {t.reviews.lean}</span>
                        )}
                        {!t.reviews.sentiment_detected && t.reviews.mentions >= t.reviews.minimum_sample && (
                          <span className="ml-1 text-muted">· no sentiment words</span>
                        )}
                      </>
                    ) : (
                      "not raised"
                    )}
                  </Cell>
                  <Cell on={t.ai_answers.present}>
                    {t.ai_answers.present
                      ? `${t.ai_answers.responses} of ${t.ai_answers.of_responses} answers`
                      : "not raised"}
                  </Cell>
                  <Cell on={t.search.present}>
                    {t.search.present
                      ? `${t.search.impressions.toLocaleString()} impressions${t.search.is_demand ? "" : " (low)"}`
                      : "no queries"}
                  </Cell>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${COVERAGE_META[t.coverage_state].cls}`}
                    >
                      {COVERAGE_META[t.coverage_state].label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {openTopic && (() => {
          const t = data.topics.find((x) => x.key === openTopic);
          if (!t) return null;
          return (
            <div className="mt-3 rounded-xl border border-line bg-surface-raised p-3 text-xs">
              <p className="font-medium">{t.label}: matched evidence</p>
              <ul className="mt-1.5 space-y-1 text-muted">
                {t.content.present && (
                  <li>
                    Site: {t.content.pages.join(", ")}
                    {t.content.matched_terms.length > 0 && ` (${t.content.matched_terms.join(", ")})`}
                  </li>
                )}
                {t.reviews.sample_quote && <li>Review: &ldquo;{t.reviews.sample_quote}&rdquo;</li>}
                {t.search.top_queries.map((q) => (
                  <li key={q.query}>
                    Search: &ldquo;{q.query}&rdquo; ({q.impressions} impressions, {q.clicks} clicks)
                  </li>
                ))}
                {t.ai_answers.present && (
                  <li>
                    AI: raised in {t.ai_answers.responses} of {t.ai_answers.of_responses} monitored answers
                  </li>
                )}
              </ul>
            </div>
          );
        })()}

        {quiet.length > 0 && (
          <p className="mt-3 text-xs text-muted">
            Not raised by any source: {quiet.map((t) => t.label).join(", ")}.
          </p>
        )}
      </section>

      <section className="rounded-2xl border border-line bg-surface/60 p-5">
        <h2 className="mb-2 text-sm font-medium">How to read this</h2>
        <ul className="space-y-1 text-xs text-muted">
          {data.limitations.map((l) => (
            <li key={l}>• {l}</li>
          ))}
          {data.deferred.map((d) => (
            <li key={d}>• Not built yet: {d}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
