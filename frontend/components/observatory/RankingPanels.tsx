"use client";

/** Two more Profound-style views, both built from evidence Beacon holds:
 *
 *   TopCitationPagesPanel  the specific pages AI answers cite (OBSERVED),
 *                          with whether each page names the property
 *                          (MEASURED: a text match over the fetched page).
 *                          Four states, never collapsed: a page Beacon could
 *                          not read is "unreachable", not "not mentioned".
 *   TopicRankingsGrid      per question, who AI names most often among the
 *                          property and its tracked competitors (MEASURED).
 */

import { useState } from "react";
import { fmtDate } from "@/lib/format";
import {
  fetchCitationPages,
  fetchTopicRankings,
  fmtRate,
  requestCitationPageCheck,
  type CitationPage,
  type MentionOnPage,
  type TopicRanking,
} from "@/lib/observatory";
import { DataLabelBadge, LoadState, Panel, ShareBar, useLoad } from "./ui";

// --- Top citation pages ------------------------------------------------------

const MENTION_STYLE: Record<MentionOnPage, { text: string; cls: string; title: string }> = {
  mentioned: { text: "Mentioned", cls: "bg-emerald-500/15 text-emerald-300", title: "The fetched page names this property" },
  not_mentioned: { text: "Not mentioned", cls: "bg-amber-500/15 text-amber-300", title: "The page was fetched and does not name this property" },
  unchecked: { text: "Unchecked", cls: "bg-surface-raised text-muted", title: "Beacon has not fetched this page yet" },
  unreachable: { text: "Unreachable", cls: "bg-rose-500/15 text-rose-300", title: "Beacon could not read this page, so nothing is claimed about it" },
};

function MentionBadge({ page }: { page: CitationPage }) {
  const s = MENTION_STYLE[page.mentioned_on_page];
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-[11px] ${s.cls}`}
      title={page.mention_detail ? `${s.title}: ${page.mention_detail}` : s.title}
    >
      {s.text}
    </span>
  );
}

export function TopCitationPagesPanel({ propertyId, days }: { propertyId: number; days: number }) {
  const [checkMsg, setCheckMsg] = useState<string | null>(null);
  const { data, error, loading, retry } = useLoad(() => fetchCitationPages(propertyId, days, 50), [propertyId, days]);

  const queueCheck = () => {
    setCheckMsg("Queuing...");
    requestCitationPageCheck(propertyId, days)
      .then((r) => setCheckMsg(r.created ? "Check queued. Results appear once the runner fetches the pages." : "A check is already queued for today."))
      .catch((e: Error) => setCheckMsg(e.message));
  };

  const unchecked = data?.check.unchecked ?? 0;
  return (
    <Panel
      title="Top citation pages"
      label="OBSERVED"
      subtitle={
        <>
          The specific pages AI answers cite for this property, by share of citations. <DataLabelBadge label="MEASURED" />{" "}
          Mentioned on page is a text match over the fetched page.
        </>
      }
      actions={
        <div className="flex items-center gap-2">
          {checkMsg && <span className="text-xs text-muted">{checkMsg}</span>}
          <button
            type="button"
            onClick={queueCheck}
            disabled={unchecked === 0}
            className="rounded-xl border border-line px-3 py-1.5 text-xs hover:bg-surface-raised disabled:opacity-50"
            title={unchecked === 0 ? "Every cited page has been checked" : `Fetch the ${unchecked} unchecked pages`}
          >
            Check unchecked pages{unchecked > 0 ? ` (${unchecked})` : ""}
          </button>
        </div>
      }
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{ when: data !== null && data.pages.length === 0, title: "No cited pages yet", body: "Pages appear once monitored AI answers cite the web." }}
      >
        {data && (
          <>
            <div className="mb-3 flex flex-wrap gap-2 text-xs text-muted">
              {(Object.keys(MENTION_STYLE) as MentionOnPage[]).map((k) => (
                <span key={k} className={`rounded-full px-2 py-0.5 ${MENTION_STYLE[k].cls}`}>
                  {MENTION_STYLE[k].text}: {data.check[k]}
                </span>
              ))}
              <span className="self-center">of {data.distinct_pages ?? data.pages.length} pages, {data.total_citations} citations</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 pr-3 font-normal">Page</th>
                    <th className="py-2 pr-3 font-normal">Type</th>
                    <th className="py-2 pr-3 text-right font-normal">Citations</th>
                    <th className="w-40 py-2 pr-3 font-normal">Share</th>
                    <th className="py-2 pr-3 font-normal">Mentioned on page</th>
                    <th className="py-2 font-normal">Checked</th>
                  </tr>
                </thead>
                <tbody>
                  {data.pages.map((p) => (
                    <tr key={p.normalized_url} className="border-b border-line/60 align-top">
                      <td className="max-w-[320px] py-2 pr-3">
                        <a href={p.url} target="_blank" rel="noreferrer" className="block truncate hover:text-violet-a" title={p.url}>
                          {p.title || p.normalized_url}
                        </a>
                        <span className="block truncate text-xs text-muted">{p.normalized_url}</span>
                      </td>
                      <td className="py-2 pr-3 text-xs text-muted">{(p.source_type ?? "other").replace(/_/g, " ")}</td>
                      <td className="py-2 pr-3 text-right">
                        {p.citations}
                        <span className="block text-xs text-muted">{p.responses} {p.responses === 1 ? "answer" : "answers"}</span>
                      </td>
                      <td className="py-2 pr-3">
                        <div className="flex items-center gap-2">
                          <ShareBar value={p.share} tone="cyan" />
                          <span className="w-10 shrink-0 text-right text-xs text-muted">{fmtRate(p.share)}</span>
                        </div>
                      </td>
                      <td className="py-2 pr-3"><MentionBadge page={p} /></td>
                      <td className="py-2 text-xs text-muted">{p.checked_at ? fmtDate(p.checked_at) : "never"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.note && <p className="mt-3 text-xs text-muted">{data.note}</p>}
          </>
        )}
      </LoadState>
    </Panel>
  );
}

// --- Topic rankings grid -----------------------------------------------------

const COLUMNS = 10;

function RankCell({ topic, rank }: { topic: TopicRanking; rank: number }) {
  const entities = topic.ranked.filter((e) => e.rank === rank);
  if (entities.length === 0) return <td className="border-l border-line/40 px-1 py-1.5" />;
  return (
    <td className="border-l border-line/40 px-1 py-1.5">
      <div className="flex flex-col gap-1">
        {entities.map((e) => (
          <span
            key={`${e.is_property ? "p" : "c"}-${e.entity_id}`}
            className={`block max-w-[120px] truncate rounded-md px-1.5 py-0.5 text-[11px] ${
              e.is_property ? "bg-violet-a/20 font-medium text-violet-a" : "bg-surface-raised text-foreground/80"
            }`}
            title={`${e.name}: named in ${e.mentions} of ${topic.answers} answers (${fmtRate(e.share)})`}
          >
            {e.name}
          </span>
        ))}
      </div>
    </td>
  );
}

export function TopicRankingsGrid({ propertyId, days }: { propertyId: number; days: number }) {
  const { data, error, loading, retry } = useLoad(() => fetchTopicRankings(propertyId, days), [propertyId, days]);
  return (
    <Panel
      title="Visibility rankings by topic"
      label="MEASURED"
      subtitle="For each question Beacon monitors, who AI names most often: this property against the competitors you track. Ties share a rank."
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{ when: data !== null && data.topics.length === 0, title: "No topics scored yet", body: "Rankings appear once monitored answers exist for this property's prompt clusters." }}
      >
        {data && (
          <>
            <div className="mb-3 flex flex-wrap gap-3 text-xs text-muted">
              <span>{data.summary.topics} topics</span>
              <span className="text-emerald-300">Leading {data.summary.leading}</span>
              <span className="text-amber-300">Needs work {data.summary.needs_work}</span>
              <span>{data.tracked_competitors} tracked competitors</span>
              <span>Minimum sample {data.minimum_sample} answers</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1100px] text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="w-64 py-2 pr-3 font-normal">Question</th>
                    <th className="py-2 pr-2 text-right font-normal">Answers</th>
                    <th className="py-2 pr-2 text-right font-normal">You</th>
                    {Array.from({ length: COLUMNS }, (_, i) => (
                      <th key={i} className="border-l border-line/40 px-1 py-2 text-center font-normal">#{i + 1}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.topics.map((t) => (
                    <tr key={t.cluster_id} className={`border-b border-line/60 ${t.needs_work ? "bg-amber-500/5" : ""}`}>
                      <td className="max-w-[16rem] py-1.5 pr-3">
                        <span className="block truncate" title={t.prompt}>{t.prompt}</span>
                        <span className="text-[11px] text-muted">
                          {t.topic_key ? t.topic_key.replace(/_/g, " ") : "prompt"}
                          {t.needs_work && <span className="ml-2 rounded-full bg-amber-500/15 px-1.5 text-amber-300">Needs work</span>}
                          {!t.sufficient && <span className="ml-2 rounded-full bg-surface-raised px-1.5">Small sample</span>}
                        </span>
                      </td>
                      <td className="py-1.5 pr-2 text-right text-muted">{t.answers}</td>
                      <td className="py-1.5 pr-2 text-right">
                        {t.property_rank !== null ? `#${t.property_rank}` : t.sufficient ? <span className="text-muted">unranked</span> : <span className="text-muted">n/a</span>}
                      </td>
                      {Array.from({ length: COLUMNS }, (_, i) => (
                        <RankCell key={i} topic={t} rank={i + 1} />
                      ))}
                    </tr>
                  ))}
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
