"use client";

/** Slice 6 panels: content gaps built from AI evidence, and AI visibility
 * shown alongside first-party Google data (association only). */

import { useState } from "react";
import {
  evaluateGaps,
  fetchGaps,
  fetchImpact,
  fmtRate,
  setGapStatus,
  type ImpactStep,
} from "@/lib/observatory";
import { DataLabelBadge, LoadState, Panel, useLoad } from "./ui";

const STATE_CHIP: Record<string, string> = {
  Actionable: "border-emerald-a/40 bg-emerald-a/10 text-emerald-a",
  "Requires confirmation": "border-amber-a/40 bg-amber-a/10 text-amber-a",
  Monitor: "border-cyan-a/40 bg-cyan-a/10 text-cyan-a",
  "Insufficient data": "border-line bg-surface-raised text-muted",
  Suppressed: "border-pink-a/40 bg-pink-a/10 text-pink-a",
};

export function ContentGapsPanel({ propertyId, days }: { propertyId: number; days: number }) {
  const [nonce, setNonce] = useState(0);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const { data, loading, error, retry } = useLoad(() => fetchGaps(propertyId), [propertyId, nonce]);

  async function reevaluate() {
    setBusy(true);
    setNote(null);
    try {
      const r = await evaluateGaps(propertyId, days);
      setNote(`${r.gaps_open} open gap${r.gaps_open === 1 ? "" : "s"}${r.auto_resolved ? `, ${r.auto_resolved} resolved since last check` : ""}.`);
      setNonce((n) => n + 1);
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Content gaps from AI answers"
      label="MODELED"
      subtitle={data?.note ?? "Questions AI answers keep answering without this property, and what its pages already say."}
      actions={
        <button onClick={reevaluate} disabled={busy} className="rounded-xl bg-violet-a px-3.5 py-2 text-sm font-medium text-background disabled:opacity-50">
          {busy ? "Checking..." : "Re-check gaps"}
        </button>
      }
    >
      {note && <p className="mb-2 text-xs text-muted">{note}</p>}
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{
          when: data !== null && data.gaps.length === 0,
          title: "No content gaps right now",
          body: "A gap needs at least 3 monitored answers to a question where the property rarely appears and competitors or cited sources show what the answers lean on.",
        }}
      >
        <ul className="space-y-3">
          {data?.gaps.map((g) => (
            <li key={g.id} className="rounded-xl border border-line bg-surface-raised p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${STATE_CHIP[g.state] ?? STATE_CHIP["Insufficient data"]}`}>
                  {g.state}
                </span>
                <span className="text-[11px] text-muted">
                  {g.impact} impact · {g.effort} effort · visible in {fmtRate(g.visibility)} of answers
                </span>
              </div>
              <p className="mt-1.5 font-medium">{g.title}</p>
              <p className="mt-1 text-sm text-muted">{g.recommendation}</p>
              {g.gate_reason && <p className="mt-1 text-xs text-amber-a">{g.gate_reason}</p>}
              <div className="mt-2 flex flex-wrap gap-1.5">
                {g.missing_terms.slice(0, 6).map((t) => (
                  <span key={t} className="rounded-full border border-dashed border-amber-a/50 px-2 py-0.5 text-[11px] text-amber-a" title="Not yet on the page">
                    + {t}
                  </span>
                ))}
                {g.covered_terms.slice(0, 4).map((t) => (
                  <span key={t} className="rounded-full border border-emerald-a/40 px-2 py-0.5 text-[11px] text-emerald-a" title="Already on a page">
                    {t}
                  </span>
                ))}
              </div>
              <details className="mt-2 text-xs text-muted">
                <summary className="cursor-pointer select-none hover:text-foreground">Evidence</summary>
                <ul className="mt-1 space-y-0.5">
                  <li>
                    Absent from {g.evidence.absent_responses ?? 0} monitored answers (responses{" "}
                    {(g.evidence.absent_response_ids ?? []).join(", ")}) <DataLabelBadge label="MEASURED" />
                  </li>
                  {(g.evidence.cited_domains ?? []).map((d) => (
                    <li key={d.domain}>
                      Cited {d.domain} ({d.citations}x, {(d.source_type ?? "other").replace(/_/g, " ")}) <DataLabelBadge label="OBSERVED" />
                    </li>
                  ))}
                  {(g.evidence.competitors_named ?? []).map((c) => (
                    <li key={c.competitor_id}>
                      Named {c.name} without the property in {c.answers} answers <DataLabelBadge label="OBSERVED" />
                    </li>
                  ))}
                </ul>
              </details>
              <div className="mt-2 flex gap-2">
                <button onClick={() => setGapStatus(g.id, "resolved").then(() => setNonce((n) => n + 1))} className="rounded-lg border border-line px-2.5 py-1 text-xs hover:bg-surface">
                  Mark done
                </button>
                <button onClick={() => setGapStatus(g.id, "dismissed").then(() => setNonce((n) => n + 1))} className="rounded-lg border border-line px-2.5 py-1 text-xs text-muted hover:bg-surface">
                  Dismiss
                </button>
              </div>
            </li>
          ))}
        </ul>
      </LoadState>
    </Panel>
  );
}

function stepValue(s: ImpactStep) {
  if (s.label === "UNAVAILABLE" || s.current === null) return "n/a";
  return s.step.startsWith("AI Visibility") ? fmtRate(s.current) : s.current.toLocaleString();
}

function stepPrevious(s: ImpactStep) {
  if (s.previous === null) return null;
  return s.step.startsWith("AI Visibility") ? fmtRate(s.previous) : s.previous.toLocaleString();
}

export function ImpactPanel({ propertyId, days }: { propertyId: number; days: number }) {
  const { data, loading, error, retry } = useLoad(() => fetchImpact(propertyId, days), [propertyId, days]);
  return (
    <Panel
      title={data?.mode === "ai_plus_search" ? "AI visibility and site traffic" : "AI visibility (connect Google for traffic context)"}
      subtitle="Side by side for the same periods. Google data adds context and is never required."
    >
      <LoadState loading={loading && !data} error={error} retry={retry}>
        {data && (
          <>
            <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {data.chain.map((s) => (
                <li key={s.step} className="rounded-xl border border-line bg-surface-raised p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-xs text-muted">{s.step}</p>
                    <DataLabelBadge label={s.label} />
                  </div>
                  <p className="mt-1 text-xl font-semibold">{stepValue(s)}</p>
                  <p className="text-[11px] text-muted">
                    {s.source}
                    {stepPrevious(s) !== null && s.label !== "UNAVAILABLE" ? ` · previous ${stepPrevious(s)}` : ""}
                  </p>
                  {s.note && <p className="mt-1 text-[11px] text-muted">{s.note}</p>}
                </li>
              ))}
            </ol>
            <p className="mt-3 text-sm">{data.alignment_text}</p>
            <p className="mt-1 text-xs text-muted">{data.note}</p>
          </>
        )}
      </LoadState>
    </Panel>
  );
}
