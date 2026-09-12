"use client";

/** Run a one-off property query and browse stored results with their
 * provider evidence (moved from the pre-Observatory AI Visibility page). */

import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import { type QueryRow, type ObservationDetail, LabelChip, type Budget, type Meta, fmtWhen } from "./shared";

export function RunQueriesPanel({ propertyId }: { propertyId: number | null }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [queries, setQueries] = useState<QueryRow[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [prompt, setPrompt] = useState("");
  const [platform, setPlatform] = useState("chatgpt");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [details, setDetails] = useState<Record<number, ObservationDetail | "loading" | "error">>({});

  function toggleQuery(id: number) {
    const next = openId === id ? null : id;
    setOpenId(next);
    if (next === null || propertyId === null || details[next]) return;
    setDetails((d) => ({ ...d, [next]: "loading" }));
    fetch(`${API_BASE}/ai-visibility/${propertyId}/${next}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((body) => setDetails((d) => ({ ...d, [next]: body.observation as ObservationDetail })))
      .catch(() => setDetails((d) => ({ ...d, [next]: "error" })));
  }

  useEffect(() => {
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
    <div className="space-y-4">
      {meta && (
        <div className="rounded-2xl border border-violet-a/30 bg-violet-a/5 px-4 py-3 text-sm text-muted">
          <span className="font-medium text-foreground">Methodology:</span>{" "}
          {meta.methodology.statement}{" "}
          <span className="text-xs">(provider: {meta.provider})</span>
        </div>
      )}
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
                  onClick={() => toggleQuery(q.id)}
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
                    <ObservationEvidence detail={details[q.id]} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ObservationEvidence({ detail }: { detail: ObservationDetail | "loading" | "error" | undefined }) {
  if (!detail || detail === "loading") {
    return <p className="text-xs text-muted">Loading provider evidence...</p>;
  }
  if (detail === "error") {
    return <p className="text-xs text-muted">Provider evidence could not be loaded.</p>;
  }
  const run = detail.run;
  return (
    <div className="space-y-3 border-t border-line pt-3">
      <div>
        <p className="mb-1 flex items-center gap-2 text-xs font-medium text-muted">
          Provider-reported citations <LabelChip label={detail.citations.label} />
        </p>
        {detail.citations.items.length ? (
          <ul className="space-y-1">
            {detail.citations.items.map((c, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2 text-xs">
                <a href={c.url} target="_blank" rel="noreferrer" className="truncate text-cyan-a hover:underline" title={c.url}>
                  {c.domain}
                </a>
                <span className="rounded-full border border-line px-1.5 py-0.5 text-[10px] text-muted">{c.source_type}</span>
                <span className="text-[10px] text-muted">{c.capture_method === "prose_regex" ? "found in text" : "provider"}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="mt-1 text-[11px] text-muted">{detail.citations.note}</p>
      </div>
      <div>
        <p className="mb-1 flex items-center gap-2 text-xs font-medium text-muted">
          Observed retrieval queries <LabelChip label={detail.search_queries.label} />
        </p>
        {detail.search_queries.items.length ? (
          <ul className="space-y-1 text-xs">
            {detail.search_queries.items.map((s, i) => (
              <li key={i} className="rounded-lg bg-surface-raised px-2 py-1">{s.query}</li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted">This provider reported no retrieval queries for this call.</p>
        )}
        <p className="mt-1 text-[11px] text-muted">{detail.search_queries.note}</p>
      </div>
      {run && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
          <span>
            Run: {run.provider}{run.model ? ` / ${run.model}` : ""}
            {run.latency_ms !== null ? ` / ${run.latency_ms} ms` : ""}
            {run.browsed === null ? "" : run.browsed ? " / browsed" : " / did not browse"}
          </span>
          <span className="flex items-center gap-1.5">
            Tokens <LabelChip label={run.tokens.label} />
            {run.tokens.input !== null ? `${run.tokens.input} in / ${run.tokens.output ?? 0} out` : "not reported"}
            {run.tokens.search_operations ? ` / ${run.tokens.search_operations} search call(s)` : ""}
          </span>
          <span className="flex items-center gap-1.5" title={run.cost.note}>
            Cost <LabelChip label={run.cost.label} />
            {run.cost.estimated_usd !== null ? `$${run.cost.estimated_usd.toFixed(4)}` : "no rate configured"}
          </span>
        </div>
      )}
    </div>
  );
}

