"use client";

/** Areas of concern: for each monitored topic, the property's AI Visibility
 * against the tracked competitor named most often, with a concern level
 * from a stated rule. Opening a topic explains the gap from stored evidence
 * only (answers, fetched pages, the property's own content). No forecasts. */

import { useState } from "react";
import { fetchConcernDetail, fetchConcerns, fmtRate, type ConcernDetail, type ConcernLevel, type ConcernTopic } from "@/lib/observatory";
import { LoadState, Panel, ShareBar, useLoad } from "./ui";

const LEVEL: Record<ConcernLevel, { text: string; cls: string }> = {
  high: { text: "High", cls: "bg-rose-500/15 text-rose-300" },
  medium: { text: "Medium", cls: "bg-amber-500/15 text-amber-300" },
  monitor: { text: "Monitor", cls: "bg-surface-raised text-muted" },
  maintain: { text: "Maintain", cls: "bg-emerald-500/15 text-emerald-300" },
  insufficient: { text: "Small sample", cls: "bg-surface-raised text-muted" },
};

function Detail({ propertyId, topic, days }: { propertyId: number; topic: ConcernTopic; days: number }) {
  const { data, error, loading, retry } = useLoad<ConcernDetail>(() => fetchConcernDetail(propertyId, topic.topic_key, days), [propertyId, topic.topic_key, days]);
  return (
    <LoadState loading={loading && !data} error={error} retry={retry}>
      {data && (
        <div className="space-y-3 rounded-xl bg-surface-raised/50 p-4 text-sm">
          <ul className="list-disc space-y-1 pl-4">
            {data.explanation.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <h4 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">Pages cited when you were left out</h4>
              {data.cited_pages.length === 0 ? (
                <p className="text-xs text-muted">Those answers cited no pages.</p>
              ) : (
                <ul className="space-y-1 text-xs">
                  {data.cited_pages.map((p) => (
                    <li key={p.url}>
                      <span className="break-all">{p.url}</span>{" "}
                      <span className="text-muted">
                        · {p.citations}x ·{" "}
                        {!p.read ? "not read yet" : p.names_you ? "names you" : "does not name you"}
                        {p.names_competitors.length > 0 && ` · names ${p.names_competitors.join(", ")}`}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h4 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">What your own site says</h4>
              <p className="text-xs text-muted">
                {data.own_content.pages === 0
                  ? "No site pages are loaded into Beacon for this property."
                  : `Best matching page: ${data.own_content.target_page}. Covers ${data.own_content.covered_terms.length} topic term${data.own_content.covered_terms.length === 1 ? "" : "s"}${
                      data.own_content.missing_terms.length ? `; missing: ${data.own_content.missing_terms.slice(0, 5).join(", ")}` : ""
                    }.`}
              </p>
              <h4 className="mb-1 mt-3 text-xs font-medium uppercase tracking-wider text-muted">Questions monitored</h4>
              <ul className="list-disc pl-4 text-xs text-muted">
                {data.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          </div>
          <div className="rounded-lg border border-line/60 px-3 py-2">
            <span className="text-xs font-medium">Recommended action</span>{" "}
            <span className="rounded-full bg-violet-a/15 px-2 py-0.5 text-[11px] text-violet-a">{data.recommended_action.state}</span>
            <p className="mt-1 text-sm">{data.recommended_action.text}</p>
            {data.recommended_action.gate_reason && <p className="mt-1 text-xs text-amber-300">{data.recommended_action.gate_reason}</p>}
          </div>
          <p className="text-[11px] text-muted">{data.note}</p>
        </div>
      )}
    </LoadState>
  );
}

export function ConcernsPanel({ propertyId, days }: { propertyId: number; days: number }) {
  const { data, error, loading, retry } = useLoad(() => fetchConcerns(propertyId, days), [propertyId, days]);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel
      title="Areas of concern"
      label="MEASURED"
      subtitle="Where AI answers leave you out by topic, against the confirmed competitor named most often. Open a topic to see why, from the evidence."
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{ when: data !== null && data.topics.length === 0, title: "No topics scored yet", body: "Topics appear once monitored answers exist for this property's prompt clusters." }}
      >
        {data && data.topics.length > 0 && (
          <>
            <div className="mb-3 flex flex-wrap gap-2 text-xs">
              {(["high", "medium", "monitor", "maintain", "insufficient"] as ConcernLevel[]).map((k) => (
                <span key={k} className={`rounded-full px-2 py-0.5 ${LEVEL[k].cls}`}>{LEVEL[k].text}: {data.summary[k] ?? 0}</span>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 pr-3 font-normal">Topic</th>
                    <th className="w-40 py-2 pr-3 font-normal">Your visibility</th>
                    <th className="py-2 pr-3 font-normal">Best competitor</th>
                    <th className="py-2 pr-3 text-right font-normal">Gap</th>
                    <th className="py-2 pr-3 font-normal">Evidence</th>
                    <th className="py-2 font-normal">Concern</th>
                  </tr>
                </thead>
                <tbody>
                  {data.topics.map((t) => {
                    const pts = t.gap_points === null ? null : Math.round(t.gap_points * 100);
                    const isOpen = open === t.topic_key;
                    return [
                      <tr
                        key={t.topic_key}
                        onClick={() => setOpen(isOpen ? null : t.topic_key)}
                        className="cursor-pointer border-b border-line/60 hover:bg-surface-raised/40"
                        aria-expanded={isOpen}
                      >
                        <td className="py-2 pr-3">
                          {t.label} <span className="text-xs text-violet-a">{isOpen ? "hide" : "why ›"}</span>
                        </td>
                        <td className="py-2 pr-3">
                          {t.visibility.value !== null ? (
                            <div className="flex items-center gap-2">
                              <ShareBar value={t.visibility.value} />
                              <span className="w-10 shrink-0 text-right text-xs">{fmtRate(t.visibility.value)}</span>
                            </div>
                          ) : (
                            <span className="text-xs text-muted">{t.visibility.numerator} of {t.answers}</span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-xs">
                          {t.best_competitor ? `${t.best_competitor.name} ${t.best_competitor.rate.value !== null ? fmtRate(t.best_competitor.rate.value) : ""}` : <span className="text-muted">none named</span>}
                        </td>
                        <td className={`py-2 pr-3 text-right text-xs ${pts !== null && pts < 0 ? "text-amber-300" : pts !== null && pts > 0 ? "text-emerald-300" : "text-muted"}`}>
                          {pts === null ? "n/a" : `${pts > 0 ? "+" : ""}${pts} pts`}
                        </td>
                        <td className="py-2 pr-3 text-xs capitalize text-muted">{t.evidence} · {t.answers}</td>
                        <td className="py-2"><span className={`rounded-full px-2 py-0.5 text-[11px] ${LEVEL[t.concern].cls}`}>{LEVEL[t.concern].text}</span></td>
                      </tr>,
                      isOpen && (
                        <tr key={`${t.topic_key}-detail`}>
                          <td colSpan={6} className="py-3">
                            <Detail propertyId={propertyId} topic={t} days={days} />
                          </td>
                        </tr>
                      ),
                    ];
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-muted">{data.note}</p>
          </>
        )}
      </LoadState>
    </Panel>
  );
}
