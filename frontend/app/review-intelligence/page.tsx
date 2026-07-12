"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, Company, Property, fetchCompanies, fetchProperties } from "@/lib/api";
import { ScopeSelect } from "@/components/ScopeSelect";

type Citation = { review_id: number | null; provider: string; excerpt: string };

type Analysis = {
  has_reviews: boolean;
  message?: string;
  score: { value: number; label: string; breakdown: { component: string; score: number; weight: number; explanation: string }[] } | null;
  overview: {
    total_reviews: number;
    average_rating: number | null;
    rating_distribution: Record<string, number>;
    most_recent_review?: string | null;
    providers?: string[];
    response_rate?: number;
    sentiment_breakdown: { positive: number; neutral: number; negative: number };
  };
  themes: { theme: string; label: string; mention_count: number; positive: number; negative: number; mixed: number; net_sentiment: number; severity: number }[];
  strengths: { label: string; positive_mentions: number; citations: Citation[] }[];
  opportunities: { priority: number; label: string; negative_mentions: number; severity_level: string; impact: string; effort: string; suggested_action: string; citations: Citation[] }[];
  trends: {
    determinable: boolean;
    note?: string;
    window_days?: number;
    metrics?: Record<string, { status: string; recent?: number; prior?: number; recent_n?: number; prior_n?: number; note?: string }>;
  };
  marketing: {
    insights: { label: string; confidence: string; positive_mentions: number; gating_status: string; gating_reason: string; caution: boolean; suggested_use: string }[];
    compliance: { level: string; message: string };
    context_guidance: { label: string; status: string }[];
  };
  property_context?: { effective_regulatory: string };
};

const SCORE_COLOR: Record<string, string> = {
  Critical: "var(--accent-pink)", "Needs Attention": "var(--accent-amber)",
  Basic: "var(--accent-amber)", Healthy: "var(--accent-cyan)", Excellent: "var(--accent-emerald)",
};
const STATUS_COLOR: Record<string, string> = {
  Improving: "text-emerald-a", Declining: "text-pink-a", Stable: "text-muted", "Insufficient data": "text-amber-a",
};
const IMPACT_COLOR: Record<string, string> = {
  High: "bg-pink-a/15 text-pink-a", Medium: "bg-amber-a/15 text-amber-a", Low: "bg-cyan-a/15 text-cyan-a",
};

export default function ReviewIntelligencePage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchProperties().then((p) => {
      setProperties(p);
      if (p.length) setPropertyId(p[0].id);
    }).catch(() => {});
    fetchCompanies().then(setCompanies).catch(() => {});
  }, []);

  const load = useCallback((id: number) => {
    setLoading(true);
    fetch(`${API_BASE}/review-intelligence/${id}`)
      .then((r) => r.json()).then(setAnalysis).finally(() => setLoading(false));
  }, []);

  useEffect(() => { if (propertyId !== null) load(propertyId); }, [propertyId, load]);

  async function analyze() {
    if (propertyId === null) return;
    setLoading(true);
    await fetch(`${API_BASE}/review-intelligence/${propertyId}/analyze`, { method: "POST" }).catch(() => {});
    load(propertyId);
  }

  const a = analysis;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Review Intelligence</h1>
          <p className="mt-1 text-sm text-muted">
            What residents praise and complain about, from your reviews. Deterministic and explainable, with citations.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <ScopeSelect
            companies={companies}
            properties={properties}
            value={propertyId}
            onChange={setPropertyId}
          />
          <button onClick={analyze} disabled={loading}
            className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50">
            {loading ? "Analyzing…" : "Analyze Property"}
          </button>
        </div>
      </div>

      {a && !a.has_reviews && (
        <div className="rounded-2xl border border-line bg-surface p-10 text-center">
          <p className="text-lg font-medium">No reviews yet</p>
          <p className="mt-1 text-sm text-muted">{a.message}</p>
        </div>
      )}

      {a && a.has_reviews && a.score && (
        <div className="space-y-6">
          {/* Overview */}
          <section className="grid gap-4 lg:grid-cols-3">
            <div className="rounded-2xl border border-line bg-surface p-5">
              <p className="text-sm text-muted">Review Health Score</p>
              <p className="mt-1 text-5xl font-semibold tracking-tight" style={{ color: SCORE_COLOR[a.score.label] }}>{a.score.value}</p>
              <p className="text-sm font-medium" style={{ color: SCORE_COLOR[a.score.label] }}>{a.score.label}</p>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted">
                <div>{a.overview.total_reviews} reviews</div>
                <div>Avg {a.overview.average_rating ?? "n/a"}</div>
                <div className="text-emerald-a">{a.overview.sentiment_breakdown.positive} positive</div>
                <div className="text-pink-a">{a.overview.sentiment_breakdown.negative} negative</div>
              </div>
            </div>
            <div className="rounded-2xl border border-line bg-surface p-5 lg:col-span-2">
              <p className="mb-3 text-sm text-muted">Score breakdown (no black boxes)</p>
              <div className="space-y-2">
                {a.score.breakdown.map((b) => (
                  <div key={b.component} className="text-sm">
                    <div className="flex justify-between">
                      <span className="capitalize">{b.component.replace(/_/g, " ")} ({Math.round(b.weight * 100)}%)</span>
                      <span className="font-medium">{b.score}</span>
                    </div>
                    <p className="text-xs text-muted">{b.explanation}</p>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* Rating distribution */}
          <section className="rounded-2xl border border-line bg-surface p-5">
            <p className="mb-3 text-sm font-medium text-muted">Rating distribution</p>
            <div className="flex items-end gap-2">
              {["5", "4", "3", "2", "1", "no_rating"].map((b) => {
                const n = a.overview.rating_distribution[b] ?? 0;
                const max = Math.max(1, ...Object.values(a.overview.rating_distribution));
                return (
                  <div key={b} className="flex flex-1 flex-col items-center gap-1">
                    <div className="flex h-24 w-full items-end">
                      <div className="w-full rounded-t bg-violet-a/60" style={{ height: `${(n / max) * 100}%` }} />
                    </div>
                    <span className="text-xs text-muted">{b === "no_rating" ? "n/a" : `${b}★`}</span>
                    <span className="text-xs font-medium">{n}</span>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Sentiment themes */}
          <section className="rounded-2xl border border-line bg-surface p-5">
            <p className="mb-3 text-sm font-medium text-muted">Sentiment themes</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {a.themes.map((t) => (
                <div key={t.theme} className="flex items-center justify-between rounded-xl bg-surface-raised px-3 py-2 text-sm">
                  <span>{t.label}</span>
                  <span className="flex gap-1.5 text-xs">
                    <span className="rounded-full bg-emerald-a/15 px-2 py-0.5 text-emerald-a">{t.positive}+</span>
                    <span className="rounded-full bg-pink-a/15 px-2 py-0.5 text-pink-a">{t.negative}−</span>
                    {t.mixed > 0 && <span className="rounded-full bg-amber-a/15 px-2 py-0.5 text-amber-a">{t.mixed} mixed</span>}
                  </span>
                </div>
              ))}
            </div>
          </section>

          {/* Operational opportunities */}
          <section className="rounded-2xl border border-line bg-surface p-5">
            <p className="mb-3 text-sm font-medium text-muted">Operational opportunities (prioritized)</p>
            <div className="space-y-3">
              {a.opportunities.length === 0 && <p className="text-sm text-muted">No recurring complaints detected.</p>}
              {a.opportunities.map((o) => (
                <div key={o.priority} className="rounded-xl bg-surface-raised p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium">{o.priority}. {o.label}</span>
                    <span className="flex gap-1.5 text-xs">
                      <span className={`rounded-full px-2 py-0.5 ${IMPACT_COLOR[o.impact]}`}>{o.impact} impact</span>
                      <span className="rounded-full border border-line px-2 py-0.5 text-muted">{o.effort} effort</span>
                      <span className="rounded-full border border-line px-2 py-0.5 text-muted">{o.negative_mentions} reviews</span>
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted">{o.suggested_action}</p>
                </div>
              ))}
            </div>
          </section>

          {/* Trends */}
          <section className="rounded-2xl border border-line bg-surface p-5">
            <p className="mb-1 text-sm font-medium text-muted">Review trends</p>
            {!a.trends.determinable ? (
              <p className="text-sm text-amber-a">{a.trends.note}</p>
            ) : (
              <>
                <p className="mb-3 text-xs text-muted">{a.trends.window_days}-day windows, anchored to the most recent review.</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {Object.entries(a.trends.metrics ?? {}).map(([name, m]) => (
                    <div key={name} className="flex items-center justify-between rounded-xl bg-surface-raised px-3 py-2 text-sm">
                      <span className="capitalize">{name.replace(/_/g, " ")}</span>
                      {m.status === "Insufficient data" ? (
                        <span className="rounded-full bg-amber-a/15 px-2 py-0.5 text-xs text-amber-a"
                          title={`recent ${m.recent_n ?? 0}, prior ${m.prior_n ?? 0}`}>insufficient data</span>
                      ) : (
                        <span className={`text-xs ${STATUS_COLOR[m.status]}`}>
                          {m.status} ({m.recent} vs {m.prior})
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>

          {/* Marketing insights */}
          <section className="rounded-2xl border border-line bg-surface p-5">
            <p className="mb-2 text-sm font-medium text-muted">Marketing insights</p>
            <div className={`mb-3 rounded-xl border p-3 text-sm ${
              a.marketing.compliance.level === "withheld" ? "border-amber-a/40 bg-amber-a/10 text-amber-a"
              : a.marketing.compliance.level === "caution" ? "border-pink-a/40 bg-pink-a/10 text-pink-a"
              : "border-line bg-surface-raised text-muted"}`}>
              <span className="font-medium">Compliance ({a.property_context?.effective_regulatory.replace("_", " ")}):</span> {a.marketing.compliance.message}
              {a.marketing.context_guidance.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {a.marketing.context_guidance.map((g) => (
                    <span key={g.label} className="rounded-full border border-current/30 px-2 py-0.5 text-[11px]">{g.label}: {g.status}</span>
                  ))}
                </div>
              )}
            </div>
            <div className="space-y-2">
              {a.marketing.insights.map((i) => (
                <div key={i.label} className="rounded-xl bg-surface-raised px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{i.label}</span>
                    <span className="flex gap-1.5 text-xs">
                      <span className="rounded-full border border-line px-2 py-0.5 text-muted capitalize">{i.confidence.replace("_", " ")}</span>
                      {i.gating_status !== "allowed" && (
                        <span className="rounded-full bg-amber-a/15 px-2 py-0.5 text-amber-a" title={i.gating_reason}>{i.gating_status}</span>
                      )}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted">{i.suggested_use}</p>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
