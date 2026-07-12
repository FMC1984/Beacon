"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, Company, Property, fetchCompanies, fetchProperties } from "@/lib/api";
import { ScopeSelect } from "@/components/ScopeSelect";

type QueryRow = {
  id: number;
  platform: string;
  prompt_text: string;
  raw_response_text: string;
  executed_at: string;
  brand_mentioned: boolean;
  sources_cited: string[] | null;
};

type Budget = {
  limit_per_day: number;
  used_today: number;
  remaining_today: number;
  exhausted: boolean;
};

type PlatformInfo = { key: string; label: string; live: boolean };
type Meta = {
  platforms: PlatformInfo[];
  methodology: { approach: string; statement: string; known_limitations: string[] };
  provider: string;
};

type Analysis = {
  has_queries: boolean;
  date_range?: { start: string; end: string };
  sample?: { total_queries: number; sufficient: boolean; minimum: number };
  mention?: { mentions: number; queries: number; rate: number | null; status: string; explanation: string } | null;
  by_platform?: {
    label: string;
    queries: number;
    mentions: number;
    mention_rate: number | null;
    mention_rate_status: string;
    top_sources: { domain: string; count: number }[];
  }[];
  source_landscape?: { domain: string; cited_in_queries: number }[];
  own_site?: { domain: string | null; status: string; explanation: string } | null;
  fact_checks?: {
    contradictions: { field: string; known_value: string; evidence: string; platform: string }[];
    cannot_verify_count: number;
  };
  score?: {
    value: number;
    grade: string;
    directional: boolean;
    breakdown: { component: string; score: number; weight: number; explanation: string }[];
  } | null;
  recommendations?: { title: string; reason: string; state: string; gate_reason: string | null }[];
  limitations?: string[];
  deferred?: string[];
};

const REC_CHIP: Record<string, string> = {
  Actionable: "bg-emerald-a/15 text-emerald-a",
  Monitor: "bg-cyan-a/15 text-cyan-a",
  "Requires confirmation": "bg-amber-a/15 text-amber-a",
  Suppressed: "bg-pink-a/15 text-pink-a",
  "Insufficient data": "bg-line/60 text-muted",
};

function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}

function fmtWhen(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function AIVisibilityPage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [queries, setQueries] = useState<QueryRow[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [tab, setTab] = useState<"Analysis" | "Run & Queries">("Analysis");
  const [prompt, setPrompt] = useState("");
  const [platform, setPlatform] = useState("chatgpt");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

  useEffect(() => {
    fetchProperties()
      .then((p) => {
        setProperties(p);
        if (p.length) setPropertyId(p[0].id);
      })
      .catch(() => setError("Could not reach the Beacon API."));
    fetchCompanies().then(setCompanies).catch(() => {});
    fetch(`${API_BASE}/ai-visibility/meta`)
      .then((r) => r.json())
      .then(setMeta)
      .catch(() => {});
  }, []);

  const load = useCallback((id: number) => {
    fetch(`${API_BASE}/ai-visibility/${id}`)
      .then((r) => r.json())
      .then((body) => {
        setQueries(body.queries ?? []);
        setBudget(body.budget ?? null);
      })
      .catch(() => setError("Could not reach the Beacon API."));
    fetch(`${API_BASE}/ai-visibility/${id}/analysis`)
      .then((r) => r.json())
      .then(setAnalysis)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (propertyId !== null) load(propertyId);
  }, [propertyId, load]);

  async function runQuery(e: React.FormEvent) {
    e.preventDefault();
    if (propertyId === null || !prompt.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/ai-visibility/${propertyId}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt.trim(), platform }),
      });
      const body = await res.json();
      if (!res.ok) {
        setError(body.detail ?? "Query failed.");
        if (res.status === 429) load(propertyId); // refresh budget state
      } else {
        setPrompt("");
        setBudget(body.budget);
        load(propertyId);
      }
    } catch {
      setError("Could not reach the Beacon API.");
    } finally {
      setBusy(false);
    }
  }

  const platformLabel = (key: string) =>
    meta?.platforms.find((p) => p.key === key)?.label ?? key;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AI Visibility</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            How the property shows up on external AI platforms. Directional
            signals from a stated sample of queries, never a precise percentage.
          </p>
        </div>
        <ScopeSelect
          companies={companies}
          properties={properties}
          value={propertyId}
          onChange={setPropertyId}
        />
      </div>

      {/* Methodology transparency (stated, not implicit). */}
      {meta && (
        <div className="rounded-2xl border border-violet-a/30 bg-violet-a/5 px-4 py-3 text-sm text-muted">
          <span className="font-medium text-foreground">Methodology:</span>{" "}
          {meta.methodology.statement}{" "}
          <span className="text-xs">(provider: {meta.provider})</span>
        </div>
      )}

      <div className="flex gap-1 border-b border-line">
        {(["Analysis", "Run & Queries"] as const).map((t) => (
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

      {tab === "Analysis" && <AnalysisPanel a={analysis} />}

      {tab === "Run & Queries" && (
      <>
      {/* Run a query */}
      <form onSubmit={runQuery} className="space-y-3 rounded-2xl border border-line bg-surface p-5">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block flex-1 text-sm">
            <span className="text-muted">Prompt to run against the AI platform</span>
            <input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. What are the best affordable apartments in Castle Rock, CO?"
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
            />
          </label>
          <label className="block text-sm">
            <span className="text-muted">Platform</span>
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="mt-1 rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
            >
              {(meta?.platforms ?? [{ key: "chatgpt", label: "ChatGPT", live: true }]).map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                  {p.live ? "" : " (not connected)"}
                </option>
              ))}
            </select>
          </label>
          <button
            disabled={busy || !prompt.trim() || Boolean(budget?.exhausted)}
            className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
          >
            {busy ? "Running…" : "Run query"}
          </button>
        </div>
        {budget && (
          <p className={`text-xs ${budget.exhausted ? "text-amber-a" : "text-muted"}`}>
            {budget.exhausted
              ? `Daily query budget reached (${budget.used_today}/${budget.limit_per_day}). External-API queries are paused until tomorrow (UTC) to keep cost bounded.`
              : `Query budget today: ${budget.used_today}/${budget.limit_per_day} used, ${budget.remaining_today} remaining.`}
          </p>
        )}
        {error && (
          <div className="rounded-xl border border-pink-a/40 bg-pink-a/10 p-2.5 text-xs text-pink-a">
            {error}
          </div>
        )}
      </form>

      {/* Results */}
      {queries.length === 0 ? (
        <div className="rounded-2xl border border-line bg-surface p-10 text-center">
          <p className="text-lg font-medium">No queries run yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted">
            Run a query above to see how this property shows up on an AI platform.
            Results are directional, from a stated sample of queries.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <h2 className="text-sm font-medium text-muted">
            Stored query results ({queries.length})
          </h2>
          {queries.map((q) => {
            const open = openId === q.id;
            return (
              <div key={q.id} className="rounded-2xl border border-line bg-surface">
                <button
                  onClick={() => setOpenId(open ? null : q.id)}
                  className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                >
                  <div className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{q.prompt_text}</span>
                    <span className="text-xs text-muted">
                      {platformLabel(q.platform)} · {fmtWhen(q.executed_at)}
                    </span>
                  </div>
                  <span className="flex shrink-0 items-center gap-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        q.brand_mentioned
                          ? "bg-emerald-a/15 text-emerald-a"
                          : "bg-line/60 text-muted"
                      }`}
                    >
                      {q.brand_mentioned ? "mentioned" : "not mentioned"}
                    </span>
                    <span className="text-xs text-muted">{open ? "−" : "+"}</span>
                  </span>
                </button>
                {open && (
                  <div className="space-y-3 border-t border-line px-4 py-3">
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted">
                        Raw response (verbatim evidence)
                      </p>
                      <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-surface-raised p-3 text-xs leading-relaxed">
                        {q.raw_response_text}
                      </pre>
                    </div>
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted">Sources cited</p>
                      {q.sources_cited && q.sources_cited.length > 0 ? (
                        <div className="flex flex-wrap gap-1.5">
                          {q.sources_cited.map((s) => (
                            <span
                              key={s}
                              className="rounded-full border border-line px-2 py-0.5 text-[11px] text-muted"
                            >
                              {s}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-muted">None detected in the response.</p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      </>
      )}
    </div>
  );
}

function AnalysisPanel({ a }: { a: Analysis | null }) {
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
                {b.score} (weight {b.weight}) — {b.explanation}
              </p>
            ))}
          </div>
        )}
      </section>

      {/* Mention by platform */}
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

      {/* Source landscape + own site */}
      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="mb-1 text-sm font-medium text-muted">Source landscape</h2>
        <p className="mb-3 text-xs text-muted">
          Which sources the AI leans on (not cross-referenced against Google
          rankings — that is deferred).
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

      {/* Fact-check findings */}
      {a.fact_checks && (a.fact_checks.contradictions.length > 0 || a.fact_checks.cannot_verify_count > 0) && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-3 text-sm font-medium text-muted">Fact-check findings</h2>
          {a.fact_checks.contradictions.map((c, i) => (
            <div key={i} className="mb-2 rounded-lg border border-amber-a/30 bg-amber-a/5 p-3 text-xs">
              <span className="font-medium text-amber-a">
                Contradiction — {c.field.replace(/_/g, " ")}
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

      {/* Deferred, stated honestly */}
      {a.deferred && a.deferred.length > 0 && (
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
