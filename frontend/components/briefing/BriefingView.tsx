"use client";

/** Monthly Strategic Briefing (Phase 17A). The flagship synthesis page:
 * hero, per-module health (explainable, no opaque composite), executive
 * summary, KPI snapshot, and top priorities. Progressive disclosure - the
 * briefing is insight-first; every status and metric links into the module it
 * came from. */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ScopeSelect } from "@/components/ScopeSelect";
import {
  Company,
  Property,
  SCOPE_STORAGE_KEY,
  fetchCompanies,
  fetchProperties,
} from "@/lib/api";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import {
  fetchBriefing,
  fetchBriefingHistory,
  generateBriefing,
  type Briefing,
  type BriefingKpi,
  type BriefingResponse,
  type BriefingSnapshot,
  type ModuleHealth,
} from "@/lib/briefing";

const STATUS_STYLE: Record<string, string> = {
  excellent: "border-emerald-a/40 bg-emerald-a/10 text-emerald-a",
  good: "border-emerald-a/40 bg-emerald-a/10 text-emerald-a",
  fair: "border-amber-a/40 bg-amber-a/10 text-amber-a",
  needs_attention: "border-pink-a/40 bg-pink-a/10 text-pink-a",
  not_enough_data: "border-line bg-surface-raised text-muted",
  not_connected: "border-line bg-surface-raised text-muted",
};

function kpiValue(k: BriefingKpi): string {
  if (k.value === null) return "n/a";
  if (k.unit === "pct") return fmtPct(k.value);
  if (k.key === "content_score") return String(k.value);
  return fmtNum(k.value);
}

function HealthCard({ m }: { m: ModuleHealth }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{m.label}</span>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${STATUS_STYLE[m.status]}`}
        >
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
          {m.status_label}
        </span>
      </div>
      <p className="mt-2 text-sm text-muted">{m.reason}</p>
      <Link href={m.details_href} className="mt-2 inline-block text-xs text-violet-a hover:underline">
        View details
      </Link>
    </div>
  );
}

function KpiCard({ k }: { k: BriefingKpi }) {
  const cmp = k.comparison;
  let changeText: string | null = null;
  let cls = "text-muted";
  if (cmp && cmp.change !== null) {
    const fmt = (n: number) => (k.unit === "pct" ? fmtPct(n) : fmtNum(n));
    const sign = cmp.change > 0 ? "+" : cmp.change < 0 ? "-" : "";
    changeText = `${sign}${fmt(Math.abs(cmp.change))}`;
    if (cmp.direction && cmp.direction !== "flat") {
      const improved = (cmp.direction === "up") === k.higher_is_better;
      cls = improved ? "text-emerald-a" : "text-pink-a";
    }
  }
  return (
    <div className="rounded-2xl border border-line bg-surface p-4">
      <p className="text-xs text-muted">{k.label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight">{kpiValue(k)}</p>
      {cmp && cmp.change !== null ? (
        <p className={`mt-1 text-xs ${cls}`}>
          {changeText}
          {cmp.previous !== null && (
            <span className="text-muted">
              {" "}
              vs {k.unit === "pct" ? fmtPct(cmp.previous) : fmtNum(cmp.previous)}
            </span>
          )}
        </p>
      ) : (
        <p className="mt-1 text-xs text-muted">No prior-month comparison</p>
      )}
    </div>
  );
}

export function BriefingBody({ data }: { data: Briefing }) {
  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="rounded-2xl border border-line bg-surface p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Monthly Strategic Briefing</h1>
            <p className="mt-1 text-sm text-muted">
              {data.property_name} · {data.period.label} · compared to{" "}
              {data.comparison_period.label}
            </p>
            {data.frozen && (
              <span className="mt-2 inline-flex items-center rounded-full border border-violet-a/40 bg-violet-a/10 px-2.5 py-0.5 text-[11px] text-violet-a">
                Frozen snapshot · generated {data.generated_at ? fmtDate(data.generated_at) : ""}
              </span>
            )}
          </div>
          <div className="text-right">
            <p className="text-3xl font-semibold tracking-tight">
              {data.health.healthy_count}
              <span className="text-lg text-muted">/{data.health.assessable_count}</span>
            </p>
            <p className="text-xs text-muted">modules healthy</p>
          </div>
        </div>
        <p className="mt-3 text-sm text-muted">{data.health.summary}</p>
      </div>

      {/* Property Health */}
      <section>
        <h2 className="mb-3 text-sm font-medium text-muted">Property health</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {data.health.modules.map((m) => (
            <HealthCard key={m.key} m={m} />
          ))}
        </div>
      </section>

      {/* Executive Summary */}
      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="text-sm font-medium">Executive summary</h2>
        {data.executive_summary.length === 0 ? (
          <p className="mt-2 text-sm text-muted">
            Not enough connected data to summarize this month yet.
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {data.executive_summary.map((item, i) => (
              <li key={i} className="text-sm leading-relaxed">
                <p>{item.text}</p>
                <p className="mt-1 text-xs text-muted">
                  {item.evidence.length > 0 && <span>Evidence: {item.evidence.join("; ")}. </span>}
                  <Link href={item.link.href} className="text-violet-a hover:underline">
                    {item.link.label}
                  </Link>
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* KPI Snapshot */}
      <section>
        <h2 className="mb-3 text-sm font-medium text-muted">Key metrics</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
          {data.kpis.map((k) => (
            <KpiCard key={k.key} k={k} />
          ))}
        </div>
      </section>

      {/* Top Priorities */}
      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="text-sm font-medium">Top priorities</h2>
        {data.top_priorities.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No prioritized actions this month.</p>
        ) : (
          <ol className="mt-3 space-y-3">
            {data.top_priorities.map((a, i) => (
              <li key={i} className="rounded-xl border border-line bg-surface-raised p-4">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm font-medium">
                    {i + 1}. {a.title}
                  </p>
                  <Link href="/opportunities" className="shrink-0 text-xs text-violet-a hover:underline">
                    View
                  </Link>
                </div>
                {a.explanation && <p className="mt-1 text-sm text-muted">{a.explanation}</p>}
                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted">
                  {a.impact && <span className="rounded-full border border-line px-2 py-0.5">Impact: {a.impact}</span>}
                  {a.effort && <span className="rounded-full border border-line px-2 py-0.5">Effort: {a.effort}</span>}
                  <span className="rounded-full border border-line px-2 py-0.5">
                    {a.supporting_signal_count} signal{a.supporting_signal_count === 1 ? "" : "s"}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      {/* Adaptive (unconnected) sections */}
      <section>
        <h2 className="mb-3 text-sm font-medium text-muted">Unlock more</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {data.adaptive_sections.map((s) => (
            <div key={s.key} className="rounded-2xl border border-dashed border-line bg-surface/50 p-4">
              <p className="text-sm font-medium">{s.label}</p>
              <p className="mt-1 text-sm text-muted">{s.message}</p>
              <span className="mt-2 inline-block text-xs text-muted/70">{s.cta} (not connected)</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export function BriefingView() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [data, setData] = useState<BriefingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [history, setHistory] = useState<BriefingSnapshot[]>([]);

  useEffect(() => {
    Promise.all([fetchCompanies(), fetchProperties()])
      .then(([cs, ps]) => {
        setCompanies(cs);
        setProperties(ps);
        // Restore a remembered property if the saved company scope names one.
        try {
          const saved = localStorage.getItem(SCOPE_STORAGE_KEY);
          if (saved && /^\d+$/.test(saved)) {
            const first = ps.find((p) => p.company_id === Number(saved));
            if (first) setPropertyId(first.id);
          }
        } catch {}
        if (ps.length === 1) setPropertyId(ps[0].id);
        setLoaded(true);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (propertyId === null) {
      setData(null);
      return;
    }
    let cancelled = false;
    setData(null);
    setError(null);
    fetchBriefing(propertyId)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [propertyId, attempt]);

  useEffect(() => {
    if (propertyId === null) return;
    fetchBriefingHistory(propertyId)
      .then((h) => setHistory(h.snapshots))
      .catch(() => setHistory([]));
  }, [propertyId, savedMsg]);

  const body = useMemo(() => {
    if (!data) return null;
    if (data.scope_required) return null;
    return data;
  }, [data]);

  async function onGenerate() {
    if (propertyId === null) return;
    setSaving(true);
    setSavedMsg(null);
    try {
      const res = await generateBriefing(propertyId);
      setSavedMsg(`Saved ${res.period.label} to Reports History.`);
    } catch (e) {
      setSavedMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ScopeSelect
          companies={companies}
          properties={properties}
          value={propertyId}
          onChange={setPropertyId}
        />
        {body && (
          <div className="flex items-center gap-2">
            {savedMsg && <span className="text-xs text-muted">{savedMsg}</span>}
            <button
              onClick={onGenerate}
              disabled={saving}
              className="rounded-xl border border-violet-a/50 bg-violet-a/15 px-3 py-2 text-sm disabled:opacity-60"
            >
              {saving ? "Saving..." : "Save snapshot"}
            </button>
          </div>
        )}
      </div>

      {error && (
        <div role="alert" className="rounded-2xl border border-pink-a/40 bg-pink-a/10 p-4 text-sm">
          <p className="text-pink-a">Could not load the briefing.</p>
          <p className="mt-1 text-muted">{error}</p>
          <button onClick={() => setAttempt((a) => a + 1)} className="mt-2 rounded-lg border border-line px-3 py-1.5 text-sm">
            Retry
          </button>
        </div>
      )}

      {!loaded ? (
        <p className="text-sm text-muted">Loading...</p>
      ) : propertyId === null ? (
        <div className="rounded-2xl border border-dashed border-line bg-surface/50 p-8 text-center">
          <p className="text-sm font-medium">Select a property</p>
          <p className="mt-1 text-sm text-muted">Choose a property to view its Monthly Strategic Briefing.</p>
        </div>
      ) : !body ? (
        !error && <p className="text-sm text-muted">Composing briefing...</p>
      ) : (
        <>
          <BriefingBody data={body} />
          {history.length > 0 && (
            <section className="rounded-2xl border border-line bg-surface p-5">
              <h2 className="text-sm font-medium">Reports history</h2>
              <ul className="mt-3 divide-y divide-line/60">
                {history.map((s) => (
                  <li key={s.id} className="flex items-center justify-between py-2 text-sm">
                    <span>{s.period_label ?? `${s.period_start} to ${s.period_end}`}</span>
                    <span className="text-xs text-muted">Saved {fmtDate(s.generated_at)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
