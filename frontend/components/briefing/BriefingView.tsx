"use client";

/** Monthly Strategic Briefing (Phase 17A). The flagship synthesis page:
 * hero, per-module health (explainable, no opaque composite), executive
 * summary, KPI snapshot, and top priorities. Progressive disclosure - the
 * briefing is insight-first; every status and metric links into the module it
 * came from. */

import { createContext, useContext, useEffect, useMemo, useState } from "react";
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
  fetchStrategist,
  generateBriefing,
  revokeBriefingShare,
  shareBriefing,
  type Strategist,
  type Briefing,
  type BriefingKpi,
  type BriefingResponse,
  type BriefingSnapshot,
  type BriefingStory,
  type CrossSystem,
  type IntelCard,
  type ModuleHealth,
  type StoryItem,
  type StrategicQuestion,
} from "@/lib/briefing";

/** Shared (public, read-only) rendering mode: Ask Nora launches are hidden
 * because a shared viewer has no access to the gated app. Module links stay
 * visible; clicking one lands on the access gate, which is honest. */
export const SharedModeContext = createContext(false);

/** Ask-Nora handoff: a link into /nora with the property and a section-aware
 * question preloaded. Nora receives the context in the question itself. */
function askNoraHref(propertyId: number, period: string, question: string): string {
  const q = `${question} (Context: Monthly Strategic Briefing, ${period}.)`;
  return `/nora?property_id=${propertyId}&q=${encodeURIComponent(q)}`;
}

function AskNora({ href }: { href: string }) {
  const shared = useContext(SharedModeContext);
  if (shared) return null;
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 rounded-lg border border-violet-a/40 bg-violet-a/10 px-2.5 py-1 text-xs text-violet-a transition-colors hover:bg-violet-a/20"
    >
      Ask Nora
    </Link>
  );
}

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

const STORY_GROUPS: { key: keyof Pick<BriefingStory, "wins" | "risks" | "trends">; title: string; empty: string; accent: string }[] = [
  { key: "wins", title: "Wins", empty: "No measured improvements versus the prior month.", accent: "text-emerald-a" },
  { key: "risks", title: "Risks", empty: "No measured declines versus the prior month.", accent: "text-pink-a" },
  { key: "trends", title: "Worth watching", empty: "No emerging patterns detected yet.", accent: "text-amber-a" },
];

function StorySection({ story, propertyId, period }: { story: BriefingStory; propertyId: number; period: string }) {
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted">This month&apos;s story</h2>
        <AskNora href={askNoraHref(propertyId, period, "Walk me through this month's wins, risks, and emerging trends.")} />
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        {STORY_GROUPS.map((g) => (
          <div key={g.key} className="rounded-2xl border border-line bg-surface p-4">
            <h3 className={`text-sm font-medium ${g.accent}`}>{g.title}</h3>
            {story[g.key].length === 0 ? (
              <p className="mt-2 text-sm text-muted">{g.empty}</p>
            ) : (
              <ul className="mt-2 space-y-3">
                {story[g.key].map((item: StoryItem, i: number) => (
                  <li key={i} className="text-sm leading-relaxed">
                    <p>{item.text}</p>
                    <p className="mt-0.5 text-xs text-muted">
                      {item.evidence.join("; ")}.{" "}
                      <Link href={item.link.href} className="text-violet-a hover:underline">
                        {item.link.label}
                      </Link>
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted">{story.note}</p>
    </section>
  );
}

const INTEL_STATE: Record<IntelCard["state"], string> = {
  ok: "border-line",
  no_data: "border-dashed border-line",
  not_connected: "border-dashed border-line",
};

function IntelCards({ cards, propertyId, period }: { cards: IntelCard[]; propertyId: number; period: string }) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-medium text-muted">Module intelligence</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {cards.map((c) => (
          <div key={c.key} className={`rounded-2xl border bg-surface p-4 ${INTEL_STATE[c.state]}`}>
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium">{c.label}</p>
              <AskNora
                href={askNoraHref(propertyId, period, `Explain what happened in ${c.label} this month and why.`)}
              />
            </div>
            <p className="mt-2 text-sm">{c.what_happened}</p>
            {c.biggest_opportunity && (
              <p className="mt-1 text-sm text-muted">
                <span className="text-foreground/70">Opportunity:</span> {c.biggest_opportunity}
              </p>
            )}
            <Link href={c.href} className="mt-2 inline-block text-xs text-violet-a hover:underline">
              Open {c.label}
            </Link>
          </div>
        ))}
      </div>
    </section>
  );
}

function CrossSystemSection({ cs }: { cs: CrossSystem }) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-medium text-muted">Cross-system insights</h2>
      {cs.insights.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-line bg-surface/50 p-4">
          <p className="text-sm text-muted">{cs.empty_reason}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {cs.insights.map((ins, i) => (
            <div key={i} className="rounded-2xl border border-line bg-surface p-4">
              <p className="text-sm font-medium">{ins.title}</p>
              <ul className="mt-2 space-y-2">
                {ins.observations.map((o, j) => (
                  <li key={j} className="text-sm leading-relaxed">
                    <p>{o.text}</p>
                    <p className="mt-0.5 text-xs text-muted">
                      {o.module}
                      {o.evidence.length > 0 && <> · {o.evidence.join("; ")}</>}
                      {" · "}
                      <Link href={o.link.href} className="text-violet-a hover:underline">
                        {o.link.label}
                      </Link>
                    </p>
                  </li>
                ))}
              </ul>
              <p className="mt-3 border-t border-line/60 pt-2 text-[11px] text-muted">{ins.framing}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function QuestionsSection({
  questions,
  propertyId,
  period,
}: {
  questions: StrategicQuestion[];
  propertyId: number;
  period: string;
}) {
  if (questions.length === 0) return null;
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h2 className="text-sm font-medium">Questions worth investigating</h2>
      <p className="mt-0.5 text-xs text-muted">
        The briefing ends with questions, not conclusions. Each launches Nora with its context.
      </p>
      <ul className="mt-3 space-y-3">
        {questions.map((q, i) => (
          <li key={i} className="rounded-xl border border-line bg-surface-raised p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium">{q.text}</p>
              <AskNora href={askNoraHref(propertyId, period, q.nora_question)} />
            </div>
            <p className="mt-1 text-xs text-muted">
              {q.why} Evidence: {q.evidence.join("; ")}.{" "}
              <Link href={q.link.href} className="text-violet-a hover:underline">
                {q.link.label}
              </Link>
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function StrategistSection({ propertyId, period }: { propertyId: number; period: { label: string; year: number; month: number } }) {
  const shared = useContext(SharedModeContext);
  const [result, setResult] = useState<Strategist | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (shared) return null;

  async function generate() {
    setBusy(true);
    setErr(null);
    try {
      setResult(await fetchStrategist(propertyId, period.year, period.month));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-2xl border border-violet-a/30 bg-violet-a/5 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium">If I were your marketing strategist</h2>
          <p className="mt-0.5 text-xs text-muted">
            With four hours this month, what would I do? Drafted from the briefing&apos;s
            numbered facts; ungrounded advice is dropped.
          </p>
        </div>
        <button
          onClick={generate}
          disabled={busy}
          title="Uses the configured AI provider; run manually to control cost."
          className="rounded-xl border border-violet-a/50 bg-violet-a/15 px-3 py-2 text-sm disabled:opacity-60"
        >
          {busy ? "Thinking..." : result ? "Regenerate" : "Generate"}
        </button>
      </div>

      {err && <p className="mt-3 text-sm text-pink-a">{err}</p>}

      {result && (
        <div className="mt-4 space-y-3">
          {result.state !== "ok" ? (
            <p className="text-sm text-muted">{result.message}</p>
          ) : (
            <>
              <ol className="space-y-3">
                {result.recommendations.map((r, i) => (
                  <li key={i} className="rounded-xl border border-line bg-surface p-4">
                    <p className="text-sm font-medium">
                      {i + 1}. {r.title}
                    </p>
                    {r.why && <p className="mt-1 text-sm text-muted">{r.why}</p>}
                    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted">
                      {r.impact && <span className="rounded-full border border-line px-2 py-0.5">Impact: {r.impact}</span>}
                      {r.effort && <span className="rounded-full border border-line px-2 py-0.5">Effort: {r.effort}</span>}
                    </div>
                    <div className="mt-2 space-y-1">
                      {r.grounding.map((g) => (
                        <p key={g.n} className="text-xs text-muted">
                          Fact {g.n}: {g.text}{" "}
                          <Link href={g.href} className="text-violet-a hover:underline">
                            source
                          </Link>
                        </p>
                      ))}
                    </div>
                  </li>
                ))}
              </ol>
              <p className="text-[11px] text-muted">{result.disclosure}</p>
            </>
          )}
        </div>
      )}
    </section>
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
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-medium">Executive summary</h2>
          <AskNora
            href={askNoraHref(
              data.property_id,
              data.period.label,
              "Explain this month's executive summary and what I should focus on."
            )}
          />
        </div>
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

      {/* This Month's Story */}
      {data.story && (
        <StorySection story={data.story} propertyId={data.property_id} period={data.period.label} />
      )}

      {/* KPI Snapshot */}
      <section>
        <h2 className="mb-3 text-sm font-medium text-muted">Key metrics</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
          {data.kpis.map((k) => (
            <KpiCard key={k.key} k={k} />
          ))}
        </div>
      </section>

      {/* Intelligence cards */}
      {data.intelligence_cards && data.intelligence_cards.length > 0 && (
        <IntelCards cards={data.intelligence_cards} propertyId={data.property_id} period={data.period.label} />
      )}

      {/* Cross-system insights */}
      {data.cross_system && <CrossSystemSection cs={data.cross_system} />}

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

      {/* Strategist synthesis (manual, grounded) */}
      <StrategistSection
        propertyId={data.property_id}
        period={{ label: data.period.label, year: data.period.year, month: data.period.month }}
      />

      {/* Strategic questions: the briefing ends with questions, not conclusions */}
      {data.strategic_questions && (
        <QuestionsSection
          questions={data.strategic_questions}
          propertyId={data.property_id}
          period={data.period.label}
        />
      )}

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

function HistoryRow({ snapshot }: { snapshot: BriefingSnapshot }) {
  const [sharePath, setSharePath] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onShare() {
    setBusy(true);
    try {
      const res = await shareBriefing(snapshot.id);
      setSharePath(res.path);
    } catch {
      setSharePath(null);
    } finally {
      setBusy(false);
    }
  }

  async function onRevoke() {
    setBusy(true);
    try {
      await revokeBriefingShare(snapshot.id);
      setSharePath(null);
      setCopied(false);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!sharePath) return;
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${sharePath}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  }

  return (
    <li className="py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>{snapshot.period_label ?? `${snapshot.period_start} to ${snapshot.period_end}`}</span>
        <span className="flex items-center gap-2">
          <span className="text-xs text-muted">Saved {fmtDate(snapshot.generated_at)}</span>
          {sharePath ? (
            <>
              <button onClick={copy} className="rounded-lg border border-line px-2 py-0.5 text-xs text-violet-a hover:bg-surface-raised">
                {copied ? "Copied" : "Copy link"}
              </button>
              <button onClick={onRevoke} disabled={busy} className="rounded-lg border border-line px-2 py-0.5 text-xs text-muted hover:text-pink-a">
                Revoke
              </button>
            </>
          ) : (
            <button onClick={onShare} disabled={busy} className="rounded-lg border border-line px-2 py-0.5 text-xs text-muted hover:text-foreground">
              {busy ? "..." : "Share"}
            </button>
          )}
        </span>
      </div>
      {sharePath && (
        <p className="mt-1 text-xs text-muted">
          Public link (anyone with it can view this frozen snapshot): {sharePath}
        </p>
      )}
    </li>
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
                  <HistoryRow key={s.id} snapshot={s} />
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
