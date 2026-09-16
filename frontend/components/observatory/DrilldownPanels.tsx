"use client";

/** The three Profound-style views Beacon already had the data for, plus the
 * evidence drawer any Observatory number can open.
 *
 *   QueryFanoutsPanel   what the AI searched for, per prompt (OBSERVED)
 *   PositionPanel       where the property fell among named brands (MEASURED)
 *   SentimentPanel      why answers read positive or negative, as topic
 *                       counts from the semantic layer (MODELED)
 *   EvidenceDrawer      the monitored answers behind any metric
 */

import { useEffect, useState } from "react";
import { EvidenceDrawerShell } from "@/components/reports/EvidenceDrawer";
import { fmtDate } from "@/lib/format";
import {
  asUtc,
  fetchEvidence,
  fetchFanouts,
  fetchPosition,
  fetchSentimentReasons,
  fmtRate,
  type Evidence,
  type EvidenceItem,
} from "@/lib/observatory";
import { DataLabelBadge, LoadState, Panel, ShareBar, useLoad } from "./ui";

// --- Evidence drawer ---------------------------------------------------------

export const EVIDENCE_LABELS: Record<string, string> = {
  ai_visibility: "AI Visibility",
  citation_rate: "Citation Rate",
  recommendation_rate: "Recommendation Rate",
  competitor_win_rate: "Competitor Win Rate",
  share_of_voice: "Share of Voice",
  citation_share: "Citation Share",
  average_position: "Average Position",
  sentiment_positive: "Positive mentions",
  sentiment_negative: "Negative mentions",
  all: "All monitored answers",
};

export function EvidenceDrawer({
  propertyId,
  metric,
  days,
  clusterId,
  onClose,
}: {
  propertyId: number;
  metric: string;
  days: number;
  clusterId?: number | null;
  onClose: () => void;
}) {
  const [onlyCounting, setOnlyCounting] = useState(true);
  const [data, setData] = useState<Evidence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchEvidence(propertyId, metric, days, { clusterId, onlyCounting })
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [propertyId, metric, days, clusterId, onlyCounting]);

  return (
    <EvidenceDrawerShell open loading={!data && !error} onClose={onClose} ariaLabel={`${EVIDENCE_LABELS[metric] ?? metric} evidence`}>
      <h2 className="text-lg font-semibold tracking-tight">{EVIDENCE_LABELS[metric] ?? metric}</h2>
      {error && <p className="mt-2 text-sm text-pink-a">{error}</p>}
      {data && (
        <>
          <p className="mt-1 text-xs text-muted">{data.description}.</p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-full border border-line bg-surface-raised px-2.5 py-0.5">
              {data.numerator} of {data.denominator} answers count
            </span>
            <label className="flex cursor-pointer items-center gap-1.5 text-muted">
              <input type="checkbox" checked={!onlyCounting} onChange={(e) => setOnlyCounting(!e.target.checked)} />
              show all {data.denominator}
            </label>
          </div>
          {data.items.length === 0 ? (
            <p className="mt-4 text-sm text-muted">No answers in this window.</p>
          ) : (
            <ul className="mt-4 divide-y divide-line/60">
              {data.items.map((it) => (
                <EvidenceRow key={it.observation_id} item={it} open={open === it.observation_id} onToggle={() => setOpen(open === it.observation_id ? null : it.observation_id)} />
              ))}
            </ul>
          )}
          {data.total > data.items.length && (
            <p className="mt-2 text-[11px] text-muted">Showing {data.items.length} of {data.total}.</p>
          )}
        </>
      )}
    </EvidenceDrawerShell>
  );
}

function EvidenceRow({ item, open, onToggle }: { item: EvidenceItem; open: boolean; onToggle: () => void }) {
  return (
    <li className={`py-2 ${item.counts ? "" : "opacity-60"}`}>
      <button onClick={onToggle} className="w-full text-left" aria-expanded={open}>
        <p className="text-xs text-muted">
          {fmtDate(asUtc(item.observed_at))} · {item.platform}
          {item.cluster ? ` · ${item.cluster}` : ""}
        </p>
        <p className="text-sm">{item.prompt}</p>
        <p className="mt-0.5 flex flex-wrap gap-2 text-[11px] text-muted">
          {item.mentioned ? <span className="text-emerald-a">named{item.mention_rank ? ` #${item.mention_rank}` : ""}</span> : <span>not named</span>}
          {item.cited && <span className="text-cyan-a">cited</span>}
          {item.recommended && <span className="text-emerald-a">recommended</span>}
          {item.sentiment && item.sentiment !== "neutral" && <span>{item.sentiment}</span>}
          {item.competitors_named > 0 && <span>{item.competitors_named} competitor{item.competitors_named === 1 ? "" : "s"} named</span>}
        </p>
      </button>
      {open && (
        <div className="mt-2 rounded-lg bg-surface-raised p-2.5 text-xs">
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap leading-relaxed">{item.answer}</pre>
          {item.citations.length > 0 && (
            <p className="mt-2 flex flex-wrap gap-1.5">
              {item.citations.map((c, i) => (
                <a key={i} href={c.url} target="_blank" rel="noreferrer" className={`rounded-full border px-2 py-0.5 text-[11px] ${c.source_type === "owned" ? "border-emerald-a/40 text-emerald-a" : "border-line text-muted"}`}>
                  {c.domain}
                </a>
              ))}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

// --- Query fanouts -----------------------------------------------------------

export function QueryFanoutsPanel({ propertyId, days }: { propertyId: number; days: number }) {
  const { data, loading, error, retry } = useLoad(() => fetchFanouts(propertyId, days), [propertyId, days]);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Panel
      title="Query fanouts"
      label="OBSERVED"
      subtitle={data?.note ?? "The searches the AI provider reported running to build each answer."}
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{ when: data !== null && data.prompts.length === 0, title: "No retrieval queries recorded", body: "Providers report the searches they ran only on some runs. None are stored for this window yet." }}
      >
        {data && (
          <>
            <p className="mb-3 text-xs text-muted">
              {data.responses_with_queries} of {data.responses} monitored answers reported their searches
              {data.coverage !== null && ` (${fmtRate(data.coverage)} coverage)`}.
            </p>
            <ul className="divide-y divide-line rounded-xl border border-line">
              {data.prompts.map((p, i) => (
                <li key={p.cluster_id ?? `b${i}`}>
                  <button onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i} className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-surface-raised">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">{p.prompt}</span>
                      <span className="text-xs text-muted">
                        {p.distinct_queries} distinct quer{p.distinct_queries === 1 ? "y" : "ies"} · {p.executions} run{p.executions === 1 ? "" : "s"}
                        {p.avg_queries_per_execution !== null && ` · ${p.avg_queries_per_execution} per run`}
                      </span>
                    </span>
                    <span className="text-xs text-muted">{open === i ? "−" : "+"}</span>
                  </button>
                  {open === i && (
                    <ul className="space-y-1.5 border-t border-line px-4 py-3">
                      {p.variations.map((v) => (
                        <li key={v.query}>
                          <div className="flex justify-between gap-2 text-sm">
                            <span className="truncate">{v.query}</span>
                            <span className="shrink-0 text-xs text-muted">{v.count} · {fmtRate(v.share)}</span>
                          </div>
                          <ShareBar value={v.share} tone="cyan" />
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </LoadState>
    </Panel>
  );
}

// --- Average position --------------------------------------------------------

export function PositionPanel({ propertyId, days, onDrill }: { propertyId: number; days: number; onDrill: (metric: string, clusterId?: number | null) => void }) {
  const { data, loading, error, retry } = useLoad(() => fetchPosition(propertyId, days), [propertyId, days]);
  return (
    <Panel title="Average position" label="MEASURED" subtitle={data?.note ?? "Where the property fell among the brands each answer named."}>
      <LoadState loading={loading && !data} error={error} retry={retry}>
        {data && (
          <>
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
              <button onClick={() => onDrill("average_position")} className="text-left hover:text-violet-a">
                <span className="text-3xl font-semibold tracking-tight">
                  {data.state === "complete" && data.current.average_position !== null ? `#${data.current.average_position}` : "n/a"}
                </span>
                <span className="ml-2 text-xs text-muted">
                  {data.state === "complete" ? `across ${data.current.ranked} answers that named it` : `needs ${data.minimum_sample} named answers; ${data.current.ranked} so far`}
                </span>
              </button>
              {data.change !== null && data.state === "complete" && (
                <span className={`text-xs ${data.change < 0 ? "text-emerald-a" : data.change > 0 ? "text-pink-a" : "text-muted"}`}>
                  {data.change > 0 ? "+" : ""}{data.change} vs previous (lower is better)
                </span>
              )}
              {data.current.first_named_rate !== null && (
                <span className="text-xs text-muted">named first in {fmtRate(data.current.first_named_rate)} of answers</span>
              )}
            </div>
            <div className="mt-3 grid grid-cols-5 gap-2">
              {Object.entries(data.current.distribution).map(([rank, n]) => (
                <div key={rank} className="rounded-lg bg-surface-raised p-2 text-center">
                  <p className="text-[11px] text-muted">#{rank}</p>
                  <p className="text-sm font-medium">{n}</p>
                </div>
              ))}
            </div>
            {data.by_prompt.length > 0 && (
              <ul className="mt-3 divide-y divide-line/60 text-sm">
                {data.by_prompt.map((r) => (
                  <li key={r.cluster_id ?? "brand"} className="flex items-center justify-between gap-3 py-1.5">
                    <button onClick={() => onDrill("average_position", r.cluster_id)} className="min-w-0 flex-1 truncate text-left hover:text-violet-a">{r.prompt}</button>
                    <span className="shrink-0 text-xs text-muted">
                      {r.state === "complete" && r.average_position !== null ? `#${r.average_position} · ${r.ranked} answers` : `${r.ranked} named, below sample`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </LoadState>
    </Panel>
  );
}

// --- Sentiment with reasons --------------------------------------------------

export function SentimentPanel({ propertyId, days, onDrill }: { propertyId: number; days: number; onDrill: (metric: string) => void }) {
  const { data, loading, error, retry } = useLoad(() => fetchSentimentReasons(propertyId, days), [propertyId, days]);
  return (
    <Panel title="Sentiment" label="MODELED" subtitle={data?.note ?? "How answers that name the property read, and which topics carry the sentiment."}>
      <LoadState loading={loading && !data} error={error} retry={retry} empty={{ when: data !== null && data.mentions === 0, title: "No mentions yet", body: "Sentiment is read from the sentence around each mention of the property." }}>
        {data && data.mentions > 0 && (
          <>
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
              <span>
                <span className="text-3xl font-semibold tracking-tight">{data.state === "complete" ? fmtRate(data.positive_share) : "n/a"}</span>
                <span className="ml-2 text-xs text-muted">positive, of answers that carried any sentiment</span>
              </span>
              <span className="text-xs text-muted">{data.counts.neutral} of {data.mentions} mentions were neutral</span>
            </div>
            <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-line/60" aria-hidden>
              <div className="bg-emerald-a" style={{ width: `${(data.counts.positive / data.mentions) * 100}%` }} />
              <div className="bg-line" style={{ width: `${(data.counts.neutral / data.mentions) * 100}%` }} />
              <div className="bg-pink-a" style={{ width: `${(data.counts.negative / data.mentions) * 100}%` }} />
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <ReasonList title="Positive because of" tone="text-emerald-a" reasons={data.positive_reasons} onDrill={() => onDrill("sentiment_positive")} count={data.counts.positive} />
              <ReasonList title="Negative because of" tone="text-pink-a" reasons={data.negative_reasons} onDrill={() => onDrill("sentiment_negative")} count={data.counts.negative} />
            </div>
          </>
        )}
      </LoadState>
    </Panel>
  );
}

function ReasonList({ title, tone, reasons, onDrill, count }: { title: string; tone: string; reasons: { topic: string; label: string; answers: number; quotes: string[] }[]; onDrill: () => void; count: number }) {
  return (
    <div>
      <button onClick={onDrill} className={`text-sm font-medium ${tone} hover:underline`}>{title} ({count})</button>
      {reasons.length === 0 ? (
        <p className="mt-1 text-xs text-muted">No topic carried this sentiment.</p>
      ) : (
        <ul className="mt-1.5 space-y-1.5">
          {reasons.map((r) => (
            <li key={r.topic} className="text-sm">
              <span>{r.label}</span>
              <span className="ml-1.5 text-xs text-muted">{r.answers} answer{r.answers === 1 ? "" : "s"}</span>
              {r.quotes[0] && <p className="truncate text-[11px] text-muted">&ldquo;{r.quotes[0]}&rdquo;</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function useEvidenceDrawer() {
  const [drill, setDrill] = useState<{ metric: string; clusterId?: number | null } | null>(null);
  return { drill, open: (metric: string, clusterId?: number | null) => setDrill({ metric, clusterId }), close: () => setDrill(null) };
}

export { DataLabelBadge };
