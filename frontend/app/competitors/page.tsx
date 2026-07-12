"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, Company, Property, fetchCompanies, fetchProperties } from "@/lib/api";
import { ScopeSelect } from "@/components/ScopeSelect";

type Competitor = {
  id: number;
  name: string;
  aliases: string[] | null;
  domain: string | null;
};

type Entity = {
  name: string;
  is_property: boolean;
  mentions: number;
  share: number | null;
};

type Analysis = {
  has_competitors: boolean;
  has_ai_data: boolean;
  competitor_count: number;
  sample?: { total_queries: number; sufficient: boolean; minimum?: number };
  date_range?: { start: string; end: string };
  share_of_voice?:
    | {
        queries: number;
        sufficient: boolean;
        total_mentions: number;
        status: string;
        entities: Entity[];
        explanation: string;
      }
    | [];
  recommendations?: { title: string; reason: string; state: string; gate_reason: string | null }[];
  limitations?: string[];
  deferred?: string[];
  directional_caveat?: string;
};

const REC_CHIP: Record<string, string> = {
  Actionable: "bg-emerald-a/15 text-emerald-a",
  Monitor: "bg-cyan-a/15 text-cyan-a",
  "Requires confirmation": "bg-amber-a/15 text-amber-a",
  Suppressed: "bg-pink-a/15 text-pink-a",
  "Insufficient data": "bg-line/60 text-muted",
};

export default function CompetitorsPage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [name, setName] = useState("");
  const [aliases, setAliases] = useState("");
  const [busy, setBusy] = useState(false);
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
    fetch(`${API_BASE}/competitors/${id}`)
      .then((r) => r.json())
      .then(setCompetitors)
      .catch(() => {});
    fetch(`${API_BASE}/competitor-intelligence/${id}`)
      .then((r) => r.json())
      .then(setAnalysis)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (propertyId !== null) load(propertyId);
  }, [propertyId, load]);

  async function addCompetitor(e: React.FormEvent) {
    e.preventDefault();
    if (propertyId === null || !name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/competitors/${propertyId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          aliases: aliases
            .split(",")
            .map((a) => a.trim())
            .filter(Boolean),
        }),
      });
      if (!res.ok) {
        setError((await res.json()).detail ?? "Could not add competitor.");
      } else {
        setName("");
        setAliases("");
        load(propertyId);
      }
    } catch {
      setError("Could not reach the Beacon API.");
    } finally {
      setBusy(false);
    }
  }

  async function removeCompetitor(id: number) {
    if (propertyId === null) return;
    await fetch(`${API_BASE}/competitors/${propertyId}/${id}`, { method: "DELETE" }).catch(() => {});
    load(propertyId);
  }

  const sov =
    analysis?.share_of_voice && !Array.isArray(analysis.share_of_voice)
      ? analysis.share_of_voice
      : null;
  const maxMentions = sov ? Math.max(1, ...sov.entities.map((e) => e.mentions)) : 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Competitor IQ</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            AI-answer share of voice: across your AI Visibility queries, how often
            ChatGPT mentions you versus competitors you name. Directional, from a
            stated sample.
          </p>
        </div>
        <ScopeSelect
          companies={companies}
          properties={properties}
          value={propertyId}
          onChange={setPropertyId}
        />
      </div>

      {error && (
        <div className="rounded-2xl border border-pink-a/40 bg-pink-a/10 p-3 text-sm text-pink-a">
          {error}
        </div>
      )}

      {/* Manage competitors */}
      <section className="space-y-3 rounded-2xl border border-line bg-surface p-5">
        <h2 className="text-sm font-medium text-muted">Tracked competitors</h2>
        <p className="text-xs text-muted">
          You name your competitors. Beacon never guesses or scrapes them.
        </p>
        <form onSubmit={addCompetitor} className="flex flex-wrap items-end gap-2">
          <label className="block text-sm">
            <span className="text-muted">Competitor name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Willow Creek Apartments"
              className="mt-1 w-56 rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
            />
          </label>
          <label className="block text-sm">
            <span className="text-muted">Aliases (comma-separated, optional)</span>
            <input
              value={aliases}
              onChange={(e) => setAliases(e.target.value)}
              placeholder="Willow Creek, WC Apts"
              className="mt-1 w-56 rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
            />
          </label>
          <button
            disabled={busy || !name.trim()}
            className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
          >
            Add
          </button>
        </form>
        {competitors.length === 0 ? (
          <p className="text-xs text-muted">No competitors tracked yet.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {competitors.map((c) => (
              <span
                key={c.id}
                className="flex items-center gap-2 rounded-full border border-line bg-surface-raised px-3 py-1 text-xs"
              >
                <span className="font-medium">{c.name}</span>
                {c.aliases && c.aliases.length > 0 && (
                  <span className="text-muted">({c.aliases.join(", ")})</span>
                )}
                <button
                  onClick={() => removeCompetitor(c.id)}
                  aria-label={`Remove ${c.name}`}
                  className="text-muted hover:text-pink-a"
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
        )}
      </section>

      {/* Share of voice */}
      {analysis && !analysis.has_competitors && (
        <div className="rounded-2xl border border-line bg-surface p-8 text-center text-sm text-muted">
          Add at least one competitor above to see AI-answer share of voice.
        </div>
      )}
      {analysis && analysis.has_competitors && !analysis.has_ai_data && (
        <div className="rounded-2xl border border-line bg-surface p-8 text-center text-sm text-muted">
          No AI Visibility queries have been run for this property yet. Run some on
          the AI Visibility page, then share of voice will populate here.
        </div>
      )}

      {sov && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-medium text-muted">AI-answer share of voice</h2>
            <span className="text-xs text-muted">
              {sov.queries} quer{sov.queries === 1 ? "y" : "ies"}
              {analysis?.date_range
                ? ` · ${analysis.date_range.start} to ${analysis.date_range.end}`
                : ""}
            </span>
          </div>
          {!sov.sufficient && (
            <p className="mb-3 rounded-lg bg-amber-a/10 px-3 py-2 text-xs text-amber-a">
              Sample is below the {analysis?.sample?.minimum ?? 3}-query minimum.
              These counts are anecdotal, not a measurement.
            </p>
          )}
          <div className="space-y-2">
            {sov.entities.map((e) => (
              <div key={e.name} className="flex items-center gap-3">
                <span
                  className={`w-48 shrink-0 truncate text-sm ${
                    e.is_property ? "font-semibold text-foreground" : ""
                  }`}
                >
                  {e.name}
                  {e.is_property ? " (you)" : ""}
                </span>
                <div className="h-4 flex-1 overflow-hidden rounded-full bg-surface-raised">
                  <div
                    className={`h-full ${e.is_property ? "bg-violet-a" : "bg-cyan-a/60"}`}
                    style={{ width: `${(e.mentions / maxMentions) * 100}%` }}
                  />
                </div>
                <span className="w-28 shrink-0 text-right text-xs text-muted">
                  {e.mentions} mention{e.mentions === 1 ? "" : "s"}
                  {e.share !== null ? ` · ${Math.round(e.share * 100)}%` : ""}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">{sov.explanation}</p>
        </section>
      )}

      {/* Recommendations */}
      {analysis?.recommendations && analysis.recommendations.length > 0 && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-3 text-sm font-medium text-muted">Recommendations</h2>
          <div className="space-y-2">
            {analysis.recommendations.map((r, i) => (
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
                {r.gate_reason && <p className="mt-1 text-xs text-amber-a">{r.gate_reason}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Deferred, stated honestly */}
      {analysis?.deferred && analysis.deferred.length > 0 && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-2 text-sm font-medium text-muted">Deliberately not measured yet</h2>
          <ul className="space-y-1 text-xs text-muted">
            {analysis.deferred.map((d, i) => (
              <li key={i}>• {d}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
