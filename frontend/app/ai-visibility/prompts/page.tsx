"use client";

import { useMemo, useState } from "react";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { RunQueriesPanel } from "@/components/observatory/legacy/RunQueriesPanel";
import { QueryFanoutsPanel } from "@/components/observatory/DrilldownPanels";
import { DataLabelBadge, LoadState, NeedsProperty, Panel, useLoad } from "@/components/observatory/ui";
import {
  fetchClusters,
  fetchOpportunity,
  fetchPrompts,
  generatePrompts,
  runMarketPrompt,
  type ObsCluster,
  type ObsPrompt,
  type Opportunity,
} from "@/lib/observatory";

const SCOPE_LABEL: Record<string, { title: string; body: string }> = {
  market: {
    title: "Market prompts",
    body: "Shared by every property in the market. One run scores all subscribed properties.",
  },
  feature: {
    title: "Feature and intent prompts",
    body: "Shared amenity and renter-intent questions; a property subscribes when it has a signal for the topic.",
  },
  brand: { title: "Brand prompts", body: "Questions that name this property or compare it with a tracked competitor." },
  sentinel: { title: "Sentinel prompts", body: "High-importance prompts watched with repeat observations." },
};

function Importance({ n }: { n: number }) {
  return (
    <span className="inline-flex gap-0.5" aria-label={`Importance ${n} of 5`} title={`Importance ${n} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span key={i} className={`h-1.5 w-1.5 rounded-full ${i <= n ? "bg-violet-a" : "bg-line"}`} />
      ))}
    </span>
  );
}

function OpportunityBadge({ opp }: { opp: Opportunity | "loading" | "error" | undefined }) {
  if (opp === undefined) return null;
  if (opp === "loading") return <span className="text-xs text-muted">Scoring...</span>;
  if (opp === "error") return <span className="text-xs text-pink-a">Could not score</span>;
  return (
    <div className="mt-3 rounded-xl border border-line bg-surface-raised p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Prompt Opportunity Score</span>
        <DataLabelBadge label={opp.data_label} />
        <span className="text-lg font-semibold">{opp.score === null ? "n/a" : `${opp.score}/100`}</span>
      </div>
      <p className="mt-1 text-muted">{opp.explanation}</p>
      <ul className="mt-2 grid gap-1 sm:grid-cols-2">
        {Object.entries(opp.contributors).map(([k, c]) => (
          <li key={k} className={c.available ? "" : "text-muted"}>
            <span className="font-medium">{k.replace(/_/g, " ")}</span>:{" "}
            {c.available ? `${Math.round((c.value ?? 0) * 100)}/100` : "UNAVAILABLE"}
            {opp.effective_weights[k] !== undefined && ` (weight ${Math.round(opp.effective_weights[k] * 100)}%)`}
            <span className="block text-muted">{c.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function PromptsPage() {
  const { propertyId, days } = useObservatory();
  const [nonce, setNonce] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const [opps, setOpps] = useState<Record<number, Opportunity | "loading" | "error">>({});
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [queued, setQueued] = useState<Record<number, string>>({});

  const clusters = useLoad(propertyId === null ? null : () => fetchClusters(propertyId), [propertyId, nonce]);
  const prompts = useLoad(propertyId === null ? null : () => fetchPrompts(propertyId), [propertyId, nonce]);

  const byCluster = useMemo(() => {
    const m = new Map<number, ObsPrompt[]>();
    for (const p of prompts.data?.prompts ?? []) {
      if (p.cluster_id === null) continue;
      m.set(p.cluster_id, [...(m.get(p.cluster_id) ?? []), p]);
    }
    return m;
  }, [prompts.data]);

  const grouped = useMemo(() => {
    const g: Record<string, ObsCluster[]> = {};
    for (const c of clusters.data?.clusters ?? []) (g[c.scope] ??= []).push(c);
    return g;
  }, [clusters.data]);

  if (propertyId === null) return <NeedsProperty />;

  function toggle(c: ObsCluster) {
    const next = open === c.id ? null : c.id;
    setOpen(next);
    if (next === null || opps[c.id] || propertyId === null) return;
    setOpps((o) => ({ ...o, [c.id]: "loading" }));
    fetchOpportunity(c.id, propertyId, days)
      .then((r) => setOpps((o) => ({ ...o, [c.id]: r })))
      .catch(() => setOpps((o) => ({ ...o, [c.id]: "error" })));
  }

  async function generate() {
    if (propertyId === null) return;
    setBusy(true);
    setNote(null);
    try {
      const r = await generatePrompts(propertyId);
      const created = (r.brand_prompts?.created ?? 0) + (r.market_prompts?.created ?? 0);
      setNote({ ok: true, text: created ? `Added ${created} prompt(s) and refreshed clusters.` : "Prompt library is already up to date." });
      setNonce((n) => n + 1);
    } catch (e) {
      setNote({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function run(p: ObsPrompt) {
    setQueued((q) => ({ ...q, [p.id]: "Queuing..." }));
    try {
      const r = await runMarketPrompt(p.id);
      setQueued((q) => ({ ...q, [p.id]: r.created ? `Queued (job ${r.job_id})` : `Already queued today (job ${r.job_id})` }));
    } catch (e) {
      setQueued((q) => ({ ...q, [p.id]: (e as Error).message }));
    }
  }

  const total = clusters.data?.total ?? 0;
  return (
    <div className="space-y-6">
      <Panel
        title="Prompt library"
        subtitle="Auto-generated from the multifamily topic taxonomy, the property's attributes, site content and Search Console topics. Wording variants are clustered so one representative runs per cluster."
        actions={
          <button
            onClick={generate}
            disabled={busy}
            className="rounded-xl bg-violet-a px-3.5 py-2 text-sm font-medium text-background disabled:opacity-50"
          >
            {busy ? "Generating..." : total ? "Refresh prompts" : "Generate prompts"}
          </button>
        }
      >
        {note && <p className={`mb-3 text-xs ${note.ok ? "text-emerald-a" : "text-pink-a"}`}>{note.text}</p>}
        <LoadState
          loading={clusters.loading && !clusters.data}
          error={clusters.error ?? prompts.error}
          retry={() => setNonce((n) => n + 1)}
          empty={{
            when: total === 0,
            title: "No prompts yet",
            body: "Generate the library to create shared market prompts for this property's city and brand prompts for the property.",
          }}
        >
          <div className="space-y-6">
            {(["market", "feature", "brand", "sentinel"] as const)
              .filter((s) => grouped[s]?.length)
              .map((scope) => (
                <div key={scope}>
                  <h3 className="text-sm font-medium">
                    {SCOPE_LABEL[scope].title} <span className="text-muted">({grouped[scope].length} clusters)</span>
                  </h3>
                  <p className="mb-2 text-xs text-muted">{SCOPE_LABEL[scope].body}</p>
                  <ul className="divide-y divide-line rounded-xl border border-line">
                    {grouped[scope].map((c) => {
                      const members = byCluster.get(c.id) ?? [];
                      const isOpen = open === c.id;
                      return (
                        <li key={c.id}>
                          <button
                            onClick={() => toggle(c)}
                            aria-expanded={isOpen}
                            className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-surface-raised"
                          >
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm">{c.label}</span>
                              <span className="text-xs text-muted">
                                {(c.topic_key ?? "general").replace(/_/g, " ")} · {c.variant_count} wording
                                {c.variant_count === 1 ? "" : "s"}
                                {c.funnel_stage ? ` · ${c.funnel_stage}` : ""}
                              </span>
                            </span>
                            <span className="flex shrink-0 items-center gap-3">
                              {c.assigned === false && (
                                <span className="rounded-full border border-line px-2 py-0.5 text-[11px] text-muted">not subscribed</span>
                              )}
                              <Importance n={c.importance} />
                              <span className="text-xs text-muted">{isOpen ? "−" : "+"}</span>
                            </span>
                          </button>
                          {isOpen && (
                            <div className="border-t border-line px-4 py-3">
                              <ul className="space-y-1.5">
                                {members.map((p) => (
                                  <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                                    <span className="min-w-0 flex-1">
                                      {p.is_representative && (
                                        <span className="mr-2 rounded-full bg-violet-a/15 px-2 py-0.5 text-[10px] font-medium text-violet-a">
                                          representative
                                        </span>
                                      )}
                                      {p.prompt_text}
                                    </span>
                                    {p.property_id === null && p.is_representative && (
                                      <span className="flex items-center gap-2">
                                        {queued[p.id] && <span className="text-xs text-muted">{queued[p.id]}</span>}
                                        <button
                                          onClick={() => run(p)}
                                          className="rounded-lg border border-line px-2.5 py-1 text-xs hover:bg-surface-raised"
                                        >
                                          Run for market
                                        </button>
                                      </span>
                                    )}
                                  </li>
                                ))}
                              </ul>
                              <OpportunityBadge opp={opps[c.id]} />
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
          </div>
        </LoadState>
      </Panel>

      <QueryFanoutsPanel propertyId={propertyId} days={days} />

      <Panel
        title="One-off property query"
        subtitle="Run a single prompt for this property now and inspect the stored answer with its provider evidence."
      >
        <RunQueriesPanel propertyId={propertyId} />
      </Panel>
    </div>
  );
}
