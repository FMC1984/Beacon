"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, Company, Property, fetchCompanies, fetchProperties } from "@/lib/api";
import { ScopeSelect } from "@/components/ScopeSelect";
import { ContentEditor } from "@/components/ContentEditor";

type Citation = {
  property_name: string;
  page: string;
  source_ref: string;
  evidence: string[];
};

type Analysis = {
  property_id: number;
  property_name: string;
  has_content: boolean;
  message?: string;
  analyzed_on?: string;
  pages_present?: string[];
  score: {
    value: number;
    grade: string;
    breakdown: { component: string; score: number; weight: number; explanation: string }[];
  } | null;
  compliance?: { level: string; message: string };
  marketing_guidance?: { theme: string; label: string; status: string; reason: string }[];
  property_context?: { property_type: string | null; effective_regulatory: string };
  keyword_intent: {
    page: string;
    mapped_keyword: string | null;
    intent_satisfied: boolean;
    topic_complete: boolean;
    covered_topics: string[];
    missing_topics: string[];
    coverage_ratio: number;
    explanation: string;
  }[];
  question_coverage: {
    summary: { answered: number; partial: number; missing: number; total: number };
    questions: {
      id: string;
      question: string;
      category: string;
      importance: string;
      status: string;
      matched_terms: string[];
      citations: Citation[];
      explanation: string;
    }[];
  };
  neighborhood: {
    rating: string;
    covered_categories: string[];
    missing_categories: string[];
    covered_count: number;
    total_categories: number;
    explanation: string;
  } | null;
  freshness: {
    determinable: boolean;
    status: string;
    findings: { page: string; issue: string; evidence: string }[];
    explanation: string;
  };
  opportunities: {
    priority: number;
    title: string;
    reason: string;
    impact: string;
    effort: string;
    citations: Citation[];
  }[];
};

const GRADE_COLOR: Record<string, string> = {
  Poor: "var(--accent-pink)",
  Basic: "var(--accent-amber)",
  Good: "var(--accent-cyan)",
  Excellent: "var(--accent-emerald)",
};

const STATUS_COLOR: Record<string, string> = {
  answered: "text-emerald-a",
  partial: "text-amber-a",
  missing: "text-pink-a",
};

const IMPACT_COLOR: Record<string, string> = {
  High: "bg-pink-a/15 text-pink-a",
  Medium: "bg-amber-a/15 text-amber-a",
  Low: "bg-cyan-a/15 text-cyan-a",
};

export default function ContentIntelligencePage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
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
    setLoading(true);
    fetch(`${API_BASE}/content-intelligence/${id}`)
      .then((r) => r.json())
      .then(setAnalysis)
      .catch(() => setError("Could not reach the Beacon API."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (propertyId !== null) load(propertyId);
  }, [propertyId, load]);

  async function analyze() {
    if (propertyId === null) return;
    setLoading(true);
    await fetch(`${API_BASE}/content-intelligence/${propertyId}/analyze`, {
      method: "POST",
    }).catch(() => {});
    load(propertyId);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Content Intelligence</h1>
          <p className="mt-1 text-sm text-muted">
            How well your website content serves renters and search intent. Every
            score is explainable and grounded in your ingested content.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <ScopeSelect
            companies={companies}
            properties={properties}
            value={propertyId}
            onChange={setPropertyId}
          />
          <button
            onClick={analyze}
            disabled={loading}
            className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
          >
            {loading ? "Analyzing…" : "Analyze Property"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl border border-pink-a/40 bg-pink-a/10 p-4 text-sm text-pink-a">
          {error}
        </div>
      )}

      {propertyId !== null && (
        <ContentEditor
          propertyId={propertyId}
          defaultUrl={properties.find((p) => p.id === propertyId)?.website_url ?? null}
          propertyType={properties.find((p) => p.id === propertyId)?.property_type}
          onChanged={() => analyze()}
        />
      )}

      {analysis && !analysis.has_content && (
        <div className="rounded-2xl border border-line bg-surface p-10 text-center">
          <p className="text-lg font-medium">No content yet</p>
          <p className="mt-1 text-sm text-muted">{analysis.message}</p>
        </div>
      )}

      {analysis && analysis.has_content && (
        <div className="space-y-6">
          {/* Compliance posture from operator-provided property context */}
          {analysis.compliance && (
            <div
              className={`rounded-2xl border p-4 text-sm ${
                analysis.compliance.level === "withheld"
                  ? "border-amber-a/40 bg-amber-a/10 text-amber-a"
                  : analysis.compliance.level === "caution"
                    ? "border-pink-a/40 bg-pink-a/10 text-pink-a"
                    : "border-line bg-surface text-muted"
              }`}
            >
              <span className="font-medium">
                Compliance ({analysis.property_context?.effective_regulatory.replace("_", " ")}):
              </span>{" "}
              {analysis.compliance.message}
              {analysis.marketing_guidance && analysis.marketing_guidance.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {analysis.marketing_guidance.map((g) => (
                    <span
                      key={g.theme}
                      title={g.reason}
                      className="rounded-full border border-current/30 px-2.5 py-1 text-[11px]"
                    >
                      {g.label}: {g.status}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Overview */}
          <section className="grid gap-4 lg:grid-cols-3">
            <div className="rounded-2xl border border-line bg-surface p-5">
              <p className="text-sm text-muted">Content Intelligence Score</p>
              <p
                className="mt-1 text-5xl font-semibold tracking-tight"
                style={{ color: GRADE_COLOR[analysis.score!.grade] }}
              >
                {analysis.score!.value}
              </p>
              <p
                className="text-sm font-medium"
                style={{ color: GRADE_COLOR[analysis.score!.grade] }}
              >
                {analysis.score!.grade}
              </p>
            </div>
            <div className="rounded-2xl border border-line bg-surface p-5 lg:col-span-2">
              <p className="mb-3 text-sm text-muted">Score breakdown (no black boxes)</p>
              <div className="space-y-2">
                {analysis.score!.breakdown.map((b) => (
                  <div key={b.component} className="text-sm">
                    <div className="flex justify-between">
                      <span className="capitalize">
                        {b.component.replace("_", " ")} ({Math.round(b.weight * 100)}%)
                      </span>
                      <span className="font-medium">{b.score}</span>
                    </div>
                    <p className="text-xs text-muted">{b.explanation}</p>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* Website Analysis (keyword intent) */}
          <section className="rounded-2xl border border-line bg-surface p-5">
            <h2 className="mb-4 text-sm font-medium text-muted">
              Website analysis: keyword intent
            </h2>
            <div className="space-y-3">
              {analysis.keyword_intent.map((r) => (
                <div key={r.page} className="rounded-xl bg-surface-raised p-4 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium capitalize">
                      {r.page.replace("_", " ")}
                      {r.mapped_keyword && (
                        <span className="ml-2 text-xs text-muted">
                          keyword: {r.mapped_keyword}
                        </span>
                      )}
                    </span>
                    <span
                      className={
                        r.intent_satisfied ? "text-emerald-a" : "text-pink-a"
                      }
                    >
                      {r.intent_satisfied ? "Satisfies intent" : "Intent gap"} (
                      {Math.round(r.coverage_ratio * 100)}%)
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted">{r.explanation}</p>
                </div>
              ))}
            </div>
          </section>

          {/* Question Coverage */}
          <section className="rounded-2xl border border-line bg-surface p-5">
            <h2 className="mb-1 text-sm font-medium text-muted">
              Renter question coverage
            </h2>
            <p className="mb-4 text-xs text-muted">
              {analysis.question_coverage.summary.answered} answered ·{" "}
              {analysis.question_coverage.summary.partial} partial ·{" "}
              {analysis.question_coverage.summary.missing} missing of{" "}
              {analysis.question_coverage.summary.total}
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {analysis.question_coverage.questions.map((q) => (
                <div
                  key={q.id}
                  className="flex items-start justify-between gap-3 rounded-xl bg-surface-raised px-3 py-2 text-sm"
                  title={
                    q.citations.length
                      ? `Evidence: ${q.citations
                          .map((c) => `${c.page} (${c.evidence.join(", ")})`)
                          .join("; ")}`
                      : q.explanation
                  }
                >
                  <span>{q.question}</span>
                  <span className={`shrink-0 capitalize ${STATUS_COLOR[q.status]}`}>
                    {q.status}
                  </span>
                </div>
              ))}
            </div>
          </section>

          {/* Neighborhood */}
          {analysis.neighborhood && (
            <section className="rounded-2xl border border-line bg-surface p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-medium text-muted">Neighborhood analysis</h2>
                <span
                  className="rounded-full px-2.5 py-1 text-xs font-medium"
                  style={{
                    background: `color-mix(in srgb, ${GRADE_COLOR[analysis.neighborhood.rating]} 15%, transparent)`,
                    color: GRADE_COLOR[analysis.neighborhood.rating],
                  }}
                >
                  {analysis.neighborhood.rating}
                </span>
              </div>
              <p className="mt-2 text-sm text-muted">{analysis.neighborhood.explanation}</p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {analysis.neighborhood.covered_categories.map((c) => (
                  <span
                    key={c}
                    className="rounded-full bg-emerald-a/15 px-2.5 py-1 text-xs text-emerald-a"
                  >
                    {c}
                  </span>
                ))}
                {analysis.neighborhood.missing_categories.map((c) => (
                  <span
                    key={c}
                    className="rounded-full border border-line px-2.5 py-1 text-xs text-muted"
                  >
                    {c}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Freshness */}
          <section className="rounded-2xl border border-line bg-surface p-5">
            <h2 className="mb-2 text-sm font-medium text-muted">Content freshness</h2>
            {!analysis.freshness.determinable ? (
              <p className="text-sm text-amber-a">{analysis.freshness.explanation}</p>
            ) : analysis.freshness.findings.length === 0 ? (
              <p className="text-sm text-emerald-a">{analysis.freshness.explanation}</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {analysis.freshness.findings.map((f, i) => (
                  <li key={i} className="text-amber-a">
                    <span className="capitalize">{f.issue}</span> on{" "}
                    <span className="capitalize">{f.page.replace("_", " ")}</span>: {f.evidence}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Opportunities */}
          <section className="rounded-2xl border border-line bg-surface p-5">
            <h2 className="mb-4 text-sm font-medium text-muted">
              Top opportunities (prioritized)
            </h2>
            <div className="space-y-3">
              {analysis.opportunities.map((o) => (
                <div key={o.priority} className="rounded-xl bg-surface-raised p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {o.priority}. {o.title}
                    </span>
                    <span className="flex gap-1.5 text-xs">
                      <span className={`rounded-full px-2 py-0.5 ${IMPACT_COLOR[o.impact]}`}>
                        {o.impact} impact
                      </span>
                      <span className="rounded-full border border-line px-2 py-0.5 text-muted">
                        {o.effort} effort
                      </span>
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted">{o.reason}</p>
                  {o.citations.length > 0 && (
                    <p className="mt-1 text-[11px] text-muted">
                      Cited:{" "}
                      {o.citations
                        .map((c) => `${c.page}${c.evidence.length ? ` (${c.evidence.join(", ")})` : ""}`)
                        .join("; ")}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
