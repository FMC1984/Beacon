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
  const [tab, setTab] = useState<"Analysis" | "Run & Queries" | "Standing & Trend">("Analysis");
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
        {(["Analysis", "Run & Queries", "Standing & Trend"] as const).map((t) => (
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

      {tab === "Standing & Trend" && propertyId !== null && (
        <StandingPanel propertyId={propertyId} />
      )}
    </div>
  );
}

type StandingPrompt = { id: number; prompt_text: string; platform: string; active: boolean };
type ScorePoint = {
  captured_at: string;
  score: number | null;
  sample_size: number;
  mention_rate: number | null;
};

function StandingPanel({ propertyId }: { propertyId: number }) {
  const [prompts, setPrompts] = useState<StandingPrompt[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [history, setHistory] = useState<ScorePoint[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    fetch(`${API_BASE}/ai-visibility/${propertyId}/prompts`)
      .then((r) => r.json())
      .then((b) => setPrompts(b.prompts ?? []))
      .catch(() => {});
    fetch(`${API_BASE}/ai-visibility/${propertyId}/prompt-suggestions`)
      .then((r) => r.json())
      .then((b) => setSuggestions(b.suggestions ?? []))
      .catch(() => {});
    fetch(`${API_BASE}/ai-visibility/${propertyId}/score-history`)
      .then((r) => r.json())
      .then((b) => setHistory(b.history ?? []))
      .catch(() => {});
  }, [propertyId]);

  useEffect(load, [load]);

  async function add(text: string) {
    if (!text.trim()) return;
    await fetch(`${API_BASE}/ai-visibility/${propertyId}/prompts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt_text: text.trim() }),
    });
    setDraft("");
    load();
  }

  async function remove(id: number) {
    await fetch(`${API_BASE}/ai-visibility/${propertyId}/prompts/${id}`, { method: "DELETE" });
    load();
  }

  async function runNow() {
    setBusy(true);
    setNote(null);
    try {
      const res = await fetch(`${API_BASE}/ai-visibility/${propertyId}/run-standing`, { method: "POST" });
      const b = await res.json();
      if (!res.ok) {
        setNote({ ok: false, text: b.detail ?? "Run failed." });
      } else {
        setNote({
          ok: true,
          text: `Ran ${b.prompts_run} prompt(s)${b.budget_hit ? " (daily budget reached, stopped early)" : ""}. ` +
            (b.score !== null ? `Score now ${b.score} (${b.sample_size} queries).` : `Sample ${b.sample_size} — still below the scoring minimum.`),
        });
      }
    } finally {
      setBusy(false);
      load();
    }
  }

  const scored = history.filter((h) => h.score !== null);
  const unusedSuggestions = suggestions.filter(
    (s) => !prompts.some((p) => p.prompt_text === s),
  );

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-line bg-surface p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium">Standing prompts</h2>
          <button
            onClick={runNow}
            disabled={busy || prompts.length === 0}
            className="rounded-lg bg-violet-a px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50"
            title={prompts.length === 0 ? "Add at least one prompt first" : "Runs all active prompts now (spends OpenAI budget)"}
          >
            {busy ? "Running…" : "Run all now"}
          </button>
        </div>
        <p className="mt-1 text-xs text-muted">
          A reusable question set. Run weekly (automatically when enabled, or with
          the button) so the property builds up enough queries to score and trend.
          Each run spends OpenAI budget, capped by the per-day limit.
        </p>
        {note && (
          <p className={`mt-2 text-xs ${note.ok ? "text-emerald-a" : "text-pink-a"}`}>{note.text}</p>
        )}

        <div className="mt-4 space-y-2">
          {prompts.length === 0 && <p className="text-sm text-muted">No standing prompts yet.</p>}
          {prompts.map((p) => (
            <div key={p.id} className="flex items-center gap-3 rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm">
              <span className="flex-1">{p.prompt_text}</span>
              <span className="text-xs text-muted">{p.platform}</span>
              <button onClick={() => remove(p.id)} className="text-xs text-muted hover:text-pink-a">✕</button>
            </div>
          ))}
        </div>

        <div className="mt-4 flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add(draft)}
            placeholder="Add a prompt a real applicant might ask an AI…"
            className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
          />
          <button onClick={() => add(draft)} disabled={!draft.trim()} className="rounded-lg border border-line px-3 py-2 text-sm text-muted hover:text-foreground disabled:opacity-50">
            Add
          </button>
        </div>

        {unusedSuggestions.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-xs text-muted">Suggested for this property type (click to add):</p>
            <div className="flex flex-wrap gap-2">
              {unusedSuggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => add(s)}
                  className="rounded-full border border-line px-3 py-1 text-xs text-muted hover:border-violet-a/60 hover:text-foreground"
                >
                  + {s}
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="text-sm font-medium">Visibility score over time</h2>
        {scored.length < 2 ? (
          <p className="mt-2 text-sm text-muted">
            {scored.length === 0
              ? "No scored runs yet. Once a run clears the query minimum, its score is plotted here; a trend appears after two or more scored runs."
              : "One scored run so far. A trend line appears after the next scored run."}
          </p>
        ) : (
          <MiniTrend points={scored} />
        )}
        {history.length > 0 && (
          <ul className="mt-4 space-y-1 text-xs text-muted">
            {history.slice(-6).reverse().map((h, i) => (
              <li key={i}>
                {fmtWhen(h.captured_at)}:{" "}
                {h.score !== null ? `score ${h.score}` : "not enough data"} ({h.sample_size} queries
                {h.mention_rate !== null ? `, ${pct(h.mention_rate)} mention rate` : ""})
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function MiniTrend({ points }: { points: ScorePoint[] }) {
  const vals = points.map((p) => p.score as number);
  const max = Math.max(100, ...vals);
  const min = Math.min(0, ...vals);
  const w = 480;
  const h = 120;
  const x = (i: number) => (points.length === 1 ? w / 2 : (i / (points.length - 1)) * (w - 20) + 10);
  const y = (v: number) => h - 10 - ((v - min) / (max - min || 1)) * (h - 20);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(p.score as number)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="mt-3 w-full" role="img" aria-label="Visibility score trend">
      <path d={path} fill="none" stroke="var(--color-violet-a, #8b7cf6)" strokeWidth="2" />
      {points.map((p, i) => (
        <circle key={i} cx={x(i)} cy={y(p.score as number)} r="3" fill="var(--color-violet-a, #8b7cf6)" />
      ))}
    </svg>
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
