"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, Company, Property, fetchCompanies, fetchProperties } from "@/lib/api";
import { ScopeSelect } from "@/components/ScopeSelect";

type Chip =
  | "Observed"
  | "Search-adjacent"
  | "Inferred"
  | "Strong signal"
  | "Supported signal"
  | "Limited signal"
  | "Cannot determine"
  | "Actionable"
  | "Monitor"
  | "Requires confirmation"
  | "Suppressed"
  | "Insufficient data";

const CHIP_CLASS: Record<string, string> = {
  Observed: "bg-cyan-a/15 text-cyan-a",
  "Search-adjacent": "bg-amber-a/15 text-amber-a",
  Inferred: "bg-violet-a/15 text-violet-a",
  "Strong signal": "bg-emerald-a/15 text-emerald-a",
  "Supported signal": "bg-cyan-a/15 text-cyan-a",
  "Limited signal": "bg-line/60 text-muted",
  "Cannot determine": "bg-line/60 text-muted",
  Actionable: "bg-emerald-a/15 text-emerald-a",
  Monitor: "bg-cyan-a/15 text-cyan-a",
  "Requires confirmation": "bg-amber-a/15 text-amber-a",
  Suppressed: "bg-pink-a/15 text-pink-a",
  "Insufficient data": "bg-line/60 text-muted",
};

function Badge({ label }: { label: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${CHIP_CLASS[label] ?? "bg-line/60 text-muted"}`}>
      {label}
    </span>
  );
}

type Analysis = {
  has_ai_traffic: boolean;
  property_name: string;
  meta: { date_range: { start: string; end: string } | null; data_source: string };
  disclaimers: { prompt_limitation: string; persistent_note: string };
  overview: {
    banner: string;
    total_ai_sessions: number;
    ai_platform_mix: { platform: string; label: string; sessions: number }[];
    top_landing_pages: { landing_page: string; sessions: number }[];
    engagement: {
      ai_engaged_sessions: number;
      ai_engagement_rate: number;
      comparison: { ai_engagement_rate: number; non_ai_engagement_rate: number } | null;
    };
    conversions: { ai_key_events: number };
    date_range: { start: string; end: string };
  } | null;
  landing_pages: {
    landing_page: string;
    sessions: number;
    engagement_rate: number;
    key_events: number;
    platform_breakdown: { label: string; sessions: number }[];
    canonical_page: string | null;
    related_topics: string[];
    ci_findings: string[];
  }[];
  search_adjacent: {
    available: boolean;
    message: string;
    associations: {
      landing_page: string;
      query_count: number;
      queries: { query: string; clicks: number; impressions: number; ctr: number; avg_position: number }[];
    }[];
  };
  inferred_topics: {
    topic: string;
    confidence: string;
    signal_types: string[];
    supporting_landing_pages: string[];
    supporting_gsc_query_count: number;
    content_covered: boolean;
    explanation: string;
    label: string;
  }[];
  renter_question_signals: {
    question: string;
    category: string;
    evidence_level: string;
    related_landing_pages: string[];
    related_gsc_query_count: number;
    content_coverage_status: string;
    recommended_action: string | null;
  }[];
  recommendations: {
    title: string;
    reason: string;
    state: string;
    evidence_level: string;
    gate_reason: string | null;
  }[];
  limitations: string[];
};

const TABS = ["Overview", "Landing Pages", "Search-Adjacent Queries", "Inferred Topics", "Limitations"] as const;
type Tab = (typeof TABS)[number];

function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}

export default function AIQuerySignalsPage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [data, setData] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Overview");

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
    fetch(`${API_BASE}/ai-query-signals/${id}`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setError("Could not reach the Beacon API."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (propertyId !== null) load(propertyId);
  }, [propertyId, load]);

  const a = data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AI Query Signals</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            What can and cannot be known about traffic from AI platforms. Every
            item is labeled as observed, search-adjacent, or inferred.
          </p>
        </div>
        <ScopeSelect
          companies={companies}
          properties={properties}
          value={propertyId}
          onChange={setPropertyId}
        />
      </div>

      {/* Persistent limitation note (always visible). */}
      <div className="rounded-2xl border border-violet-a/30 bg-violet-a/5 px-4 py-3 text-sm text-muted">
        AI platforms generally do not pass the exact question or prompt used by a
        visitor. Beacon shows observed referral data, related search signals, and
        clearly labeled topic inferences.
      </div>

      {error && (
        <div className="rounded-2xl border border-pink-a/40 bg-pink-a/10 p-4 text-sm text-pink-a">
          {error}
        </div>
      )}
      {loading && !a && <p className="text-muted">Loading…</p>}

      {a && !a.has_ai_traffic && (
        <div className="rounded-2xl border border-line bg-surface p-10 text-center">
          <p className="text-lg font-medium">No AI-referred traffic yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted">
            No AI-referred sessions are recorded for this property in the ingested
            data, so there are no signals to analyze.
          </p>
        </div>
      )}

      {a && a.has_ai_traffic && a.overview && (
        <>
          <div className="flex flex-wrap gap-1 border-b border-line">
            {TABS.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-t-lg px-3 py-2 text-sm transition-colors ${
                  tab === t
                    ? "border-b-2 border-violet-a font-medium text-foreground"
                    : "text-muted hover:text-foreground"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {tab === "Overview" && <Overview a={a} />}
          {tab === "Landing Pages" && <LandingPages a={a} />}
          {tab === "Search-Adjacent Queries" && <SearchAdjacent a={a} />}
          {tab === "Inferred Topics" && <Inferred a={a} />}
          {tab === "Limitations" && <Limitations a={a} />}

          {/* Recommendations always shown below the tabs. */}
          <Recommendations a={a} />
        </>
      )}
    </div>
  );
}

function Overview({ a }: { a: Analysis }) {
  const ov = a.overview!;
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-cyan-a/30 bg-cyan-a/5 px-4 py-3 text-sm text-muted">
        {ov.banner}
      </div>
      <section className="rounded-2xl border border-line bg-surface p-5">
        <div className="mb-4 flex items-center gap-2">
          <Badge label="Observed" />
          <span className="text-xs text-muted">
            {ov.date_range.start} to {ov.date_range.end}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Metric label="AI-referred sessions" value={ov.total_ai_sessions.toLocaleString()} />
          <Metric label="AI-referred conversions" value={ov.conversions.ai_key_events.toLocaleString()} />
          <Metric label="AI engagement rate" value={pct(ov.engagement.ai_engagement_rate)} />
          <Metric
            label="vs non-AI engagement"
            value={
              ov.engagement.comparison
                ? pct(ov.engagement.comparison.non_ai_engagement_rate)
                : "insufficient data"
            }
          />
        </div>
      </section>
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-3 text-sm font-medium text-muted">AI platform mix</h2>
          <div className="space-y-2">
            {ov.ai_platform_mix.map((p) => (
              <div key={p.platform} className="flex items-center justify-between text-sm">
                <span>{p.label}</span>
                <span className="font-semibold">{p.sessions.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </section>
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-3 text-sm font-medium text-muted">Top AI-referred landing pages</h2>
          <div className="space-y-2">
            {ov.top_landing_pages.map((p) => (
              <div key={p.landing_page} className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate">{p.landing_page}</span>
                <span className="shrink-0 font-semibold">{p.sessions.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function LandingPages({ a }: { a: Analysis }) {
  return (
    <div className="space-y-3">
      {a.landing_pages.map((lp) => (
        <section key={lp.landing_page} className="rounded-2xl border border-line bg-surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Badge label="Observed" />
              <span className="font-medium">{lp.landing_page}</span>
            </div>
            <span className="text-sm text-muted">
              {lp.sessions} sessions · {pct(lp.engagement_rate)} engaged · {lp.key_events} conversions
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-muted">
            {lp.platform_breakdown.map((p) => (
              <span key={p.label} className="rounded-full border border-line px-2 py-0.5">
                {p.label} {p.sessions}
              </span>
            ))}
          </div>
          {lp.related_topics.length > 0 && (
            <p className="mt-2 text-xs text-muted">
              Associated content topics: {lp.related_topics.join(", ")}
            </p>
          )}
          {lp.ci_findings.map((f, i) => (
            <p key={i} className="mt-1 text-xs text-muted">
              {f}
            </p>
          ))}
        </section>
      ))}
    </div>
  );
}

function SearchAdjacent({ a }: { a: Analysis }) {
  const sa = a.search_adjacent;
  if (!sa.available) {
    return (
      <div className="rounded-2xl border border-line bg-surface p-8 text-center text-sm text-muted">
        {sa.message}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-amber-a/30 bg-amber-a/5 px-4 py-3 text-sm text-muted">
        {sa.message}
      </div>
      {sa.associations.map((assoc) => (
        <section key={assoc.landing_page} className="rounded-2xl border border-line bg-surface p-5">
          <div className="mb-3 flex items-center gap-2">
            <Badge label="Search-adjacent" />
            <span className="font-medium">{assoc.landing_page}</span>
            <span className="text-xs text-muted">{assoc.query_count} related Google searches</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-muted">
                <tr>
                  <th className="py-1 pr-4">Google Search query</th>
                  <th className="py-1 pr-4">Clicks</th>
                  <th className="py-1 pr-4">Impressions</th>
                  <th className="py-1 pr-4">CTR</th>
                  <th className="py-1">Avg pos</th>
                </tr>
              </thead>
              <tbody>
                {assoc.queries.map((q) => (
                  <tr key={q.query} className="border-t border-line/60">
                    <td className="py-1.5 pr-4">{q.query}</td>
                    <td className="py-1.5 pr-4">{q.clicks}</td>
                    <td className="py-1.5 pr-4">{q.impressions}</td>
                    <td className="py-1.5 pr-4">{pct(q.ctr)}</td>
                    <td className="py-1.5">{q.avg_position}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

function Inferred({ a }: { a: Analysis }) {
  const hasTopics = a.inferred_topics.length > 0;
  const hasQuestions = a.renter_question_signals.length > 0;
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-violet-a/30 bg-violet-a/5 px-4 py-3 text-xs text-muted">
        Inferred from landing-page and content signals. These are not actual AI prompts.
      </div>
      {!hasTopics && !hasQuestions && (
        <div className="rounded-2xl border border-line bg-surface p-8 text-center text-sm text-muted">
          No topics could be inferred. This usually means landing pages are not
          present in the ingested GA4 export, so there is nothing to map to
          content or search signals.
        </div>
      )}
      {hasTopics && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-muted">Inferred topics</h2>
          {a.inferred_topics.map((t) => (
            <div key={t.topic} className="rounded-2xl border border-line bg-surface p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge label="Inferred" />
                <Badge label={t.confidence} />
                <span className="font-medium">{t.topic}</span>
              </div>
              <p className="mt-1.5 text-sm text-muted">{t.explanation}</p>
            </div>
          ))}
        </section>
      )}
      {hasQuestions && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-muted">Renter question signals</h2>
          {a.renter_question_signals.map((s) => (
            <div key={s.question} className="rounded-2xl border border-line bg-surface p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge label="Inferred" />
                <Badge label={s.evidence_level} />
                <span className="font-medium">{s.question}</span>
                <span className="text-xs text-muted">content: {s.content_coverage_status}</span>
              </div>
              {s.recommended_action && (
                <p className="mt-1.5 text-sm text-muted">{s.recommended_action}</p>
              )}
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function Limitations({ a }: { a: Analysis }) {
  return (
    <ul className="space-y-2">
      {a.limitations.map((l, i) => (
        <li
          key={i}
          className="rounded-xl border border-line bg-surface px-4 py-3 text-sm text-muted"
        >
          {l}
        </li>
      ))}
    </ul>
  );
}

function Recommendations({ a }: { a: Analysis }) {
  if (a.recommendations.length === 0) {
    return (
      <section className="rounded-2xl border border-line bg-surface p-5">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-medium text-muted">Recommendations</h2>
          <Badge label="Insufficient data" />
        </div>
        <p className="mt-2 text-sm text-muted">
          No evidence-backed recommendations met the confidence and volume bar for
          this period.
        </p>
      </section>
    );
  }
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h2 className="mb-3 text-sm font-medium text-muted">Recommendations</h2>
      <div className="space-y-2">
        {a.recommendations.map((r, i) => (
          <div key={i} className="rounded-xl border border-line bg-surface-raised p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge label={r.state} />
              <span className="font-medium">{r.title}</span>
            </div>
            <p className="mt-1.5 text-sm text-muted">{r.reason}</p>
            {r.gate_reason && (
              <p className="mt-1 text-xs text-amber-a">{r.gate_reason}</p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-0.5 text-xl font-semibold">{value}</p>
    </div>
  );
}
