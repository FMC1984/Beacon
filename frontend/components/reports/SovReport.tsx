"use client";

/** AI Share of Voice report (Phase 18B). Property Mentions / (Property +
 * Competitor Mentions) in tested AI responses, drillable from the overview
 * number all the way down to the individual response and mention that
 * produced it: Overview -> Trend -> by-Platform / by-Topic -> Topic ->
 * Prompt -> response evidence. Distinct from AI Visibility and Citation
 * Share - never fused with either. Percentage-point comparisons only
 * ("+6 pts"), never a relative percentage on top of a percentage. */

import { useEffect, useState } from "react";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import {
  fetchSovEvidence,
  fetchSovPromptDrilldown,
  fetchSovReport,
  fetchSovTopicDrilldown,
  type SovByTopicRow,
  type SovEvidence,
  type SovPromptDrilldown,
  type SovReport as SovReportData,
  type SovTopicDrilldown,
} from "@/lib/reports";
import { EmptyState, ErrorState, StateBadge } from "./DataStates";
import { EvidenceDrawerShell, EvidenceField } from "./EvidenceDrawer";
import { ReportMetricCard } from "./ReportMetricCard";
import { SovRankingPanel } from "./SovRankingPanel";
import { useReportContext } from "./ReportContext";

type View =
  | { type: "overview" }
  | { type: "topic"; topicId: number }
  | { type: "prompt"; topicId: number; promptId: number };

const TREND_ARROW: Record<string, string> = { up: "↑", down: "↓", flat: "→" };

function Section({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h3 className="text-sm font-medium">{title}</h3>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Overview({
  report,
  onOpenRanking,
}: {
  report: Extract<SovReportData, { has_competitors: true }>;
  onOpenRanking: () => void;
}) {
  const ov = report.overview;
  const rankLabel = ov.rank !== null ? `#${ov.rank} of ${ov.rank_of}${ov.tied ? " (tied)" : ""}` : undefined;
  const pa = report.portfolio_average;
  const portfolioNote = pa.available
    ? `Portfolio average (${pa.property_count} other propert${pa.property_count === 1 ? "y" : "ies"}): ${fmtPct(pa.average_share_of_voice)}`
    : undefined;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div title={report.tooltips.ai_share_of_voice}>
        <ReportMetricCard
          label="AI Share of Voice"
          state={ov.sufficient ? "complete" : "insufficient_sample"}
          stateDetail={`${ov.sample_size} tested response(s); below the visibility sample minimum.`}
          value={ov.share_of_voice !== null ? fmtPct(ov.share_of_voice) : undefined}
          comparison={ov.comparison}
          changeMode="points"
          source="AI Share of Voice"
          lastDataDate={report.generated_on}
          sample={{ numerator: ov.property_mentions, denominator: ov.total_mentions, unit: "of all mentions" }}
          subText={portfolioNote}
        />
      </div>
      <button onClick={onOpenRanking} className="text-left">
        <ReportMetricCard
          label="Competitive rank"
          state={ov.rank !== null ? "complete" : "insufficient_sample"}
          stateDetail="Not enough data yet to rank against competitors."
          value={rankLabel}
          source="AI Share of Voice"
          lastDataDate={report.generated_on}
          subText="Click for full ranking and winners/losers"
        />
      </button>
      <ReportMetricCard
        label="Property mentions"
        state="complete"
        value={fmtNum(ov.property_mentions)}
        source="AI Share of Voice"
        lastDataDate={report.generated_on}
      />
      <ReportMetricCard
        label="Eligible tested responses"
        state="complete"
        value={fmtNum(ov.eligible_responses)}
        source="AI Share of Voice"
        lastDataDate={report.generated_on}
      />
    </div>
  );
}

function Trend({ report }: { report: Extract<SovReportData, { has_competitors: true }> }) {
  const t = report.trend;
  if (t.points.length === 0) {
    return <EmptyState title="No trend yet" body="Not enough tested responses to build a trend line." />;
  }
  return (
    <div>
      <ul className="space-y-1 text-sm">
        {t.points.map((p, i) => (
          <li key={i} className="flex items-center gap-3">
            <span className="w-28 text-muted">{p.period}</span>
            <span className="w-20">
              {p.sufficient && p.share_of_voice !== null ? fmtPct(p.share_of_voice) : "insufficient"}
            </span>
            <span className="text-xs text-muted">{p.sample_size} responses</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted">{t.note}</p>
    </div>
  );
}

function ByPlatform({ report }: { report: Extract<SovReportData, { has_competitors: true }> }) {
  const rows = report.by_platform;
  if (rows.length === 0) {
    return <EmptyState title="No platform data yet" body="No tested responses in this window." />;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-left text-xs font-medium text-muted">
            <th className="pb-2 pr-3">Platform</th>
            <th className="pb-2 pr-3">Share of Voice</th>
            <th className="pb-2 pr-3">Top competitor</th>
            <th className="pb-2 pr-3">Rank</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.platform} className="border-t border-line/50">
              <td className="py-2 pr-3">{r.platform_label}</td>
              <td className="py-2 pr-3">
                {r.sufficient && r.share_of_voice !== null ? (
                  fmtPct(r.share_of_voice)
                ) : (
                  <StateBadge state="insufficient_sample" />
                )}
              </td>
              <td className="py-2 pr-3 text-muted">
                {r.top_competitor ? `${r.top_competitor.name} (${fmtPct(r.top_competitor.share_of_voice)})` : "—"}
              </td>
              <td className="py-2 pr-3 text-muted">{r.rank !== null ? `#${r.rank} of ${r.rank_of}` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ByTopic({
  rows,
  onOpenTopic,
}: {
  rows: SovByTopicRow[];
  onOpenTopic: (topicId: number) => void;
}) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No topics configured"
        body="Add AI Topics on the AI Visibility page to see Share of Voice broken out by subject. Overall Share of Voice can hide topic-level weakness."
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-left text-xs font-medium text-muted">
            <th className="pb-2 pr-3">Topic</th>
            <th className="pb-2 pr-3">Share of Voice</th>
            <th className="pb-2 pr-3">Leader</th>
            <th className="pb-2 pr-3">Gap to leader</th>
            <th className="pb-2 pr-3">Trend</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.topic_id}
              className="cursor-pointer border-t border-line/50 hover:bg-surface-raised"
              onClick={() => onOpenTopic(r.topic_id)}
            >
              <td className="py-2 pr-3 font-medium">{r.topic_name}</td>
              <td className="py-2 pr-3">
                {r.sufficient && r.share_of_voice !== null ? (
                  fmtPct(r.share_of_voice)
                ) : (
                  <StateBadge state="insufficient_sample" />
                )}
              </td>
              <td className="py-2 pr-3 text-muted">
                {r.leader ? `${r.leader.name}${r.leader.is_property ? " (you)" : ""}` : "—"}
              </td>
              <td className="py-2 pr-3 text-muted">{r.gap_to_leader !== null ? fmtPct(r.gap_to_leader) : "—"}</td>
              <td className="py-2 pr-3 text-muted">
                {r.trend_arrow ? TREND_ARROW[r.trend_arrow] : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TopicDrilldown({
  data,
  onBack,
  onOpenPrompt,
}: {
  data: SovTopicDrilldown;
  onBack: () => void;
  onOpenPrompt: (promptId: number) => void;
}) {
  return (
    <Section title={data.topic.topic_name} sub={data.topic.description ?? undefined}>
      <button onClick={onBack} className="mb-4 text-xs text-muted hover:text-foreground">
        ← Back to overview
      </button>
      {data.prompts.length === 0 ? (
        <EmptyState title="No prompts under this topic" body="Assign standing prompts to this topic on the AI Visibility page." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-xs font-medium text-muted">
                <th className="pb-2 pr-3">Prompt</th>
                <th className="pb-2 pr-3">Platform</th>
                <th className="pb-2 pr-3">Share of Voice</th>
                <th className="pb-2 pr-3">Mentioned</th>
                <th className="pb-2 pr-3">Leader</th>
              </tr>
            </thead>
            <tbody>
              {data.prompts.map((p) => (
                <tr
                  key={p.prompt_id}
                  className="cursor-pointer border-t border-line/50 hover:bg-surface-raised"
                  onClick={() => onOpenPrompt(p.prompt_id)}
                >
                  <td className="max-w-[22rem] truncate py-2 pr-3" title={p.prompt_text}>{p.prompt_text}</td>
                  <td className="py-2 pr-3 text-muted">{p.platform}</td>
                  <td className="py-2 pr-3">
                    {p.sufficient && p.share_of_voice !== null ? fmtPct(p.share_of_voice) : <StateBadge state="insufficient_sample" />}
                  </td>
                  <td className="py-2 pr-3">{p.mentioned ? "Yes" : "No"}</td>
                  <td className="py-2 pr-3 text-muted">
                    {p.leader ? `${p.leader.name} (${fmtPct(p.leader.share_of_voice)})` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function PromptDrilldown({
  data,
  onBack,
  onOpenEvidence,
}: {
  data: SovPromptDrilldown;
  onBack: () => void;
  onOpenEvidence: (responseId: number) => void;
}) {
  return (
    <Section title={data.prompt.prompt_text} sub="Every tested response for this prompt in the current window.">
      <button onClick={onBack} className="mb-4 text-xs text-muted hover:text-foreground">
        ← Back to topic
      </button>
      {data.responses.length === 0 ? (
        <EmptyState title="No responses in this window" body="No AI Visibility runs for this prompt in the selected date range." />
      ) : (
        <ul className="space-y-2">
          {data.responses.map((r) => (
            <li
              key={r.response_id}
              className="flex cursor-pointer items-center gap-3 rounded-xl border border-line p-3 text-sm hover:bg-surface-raised"
              onClick={() => onOpenEvidence(r.response_id)}
            >
              <span className="w-24 shrink-0 text-muted">{r.platform_label}</span>
              <span className="w-28 shrink-0 text-muted">{fmtDate(r.run_date)}</span>
              <span className={`w-24 shrink-0 ${r.mentioned ? "text-emerald-a" : "text-muted"}`}>
                {r.mentioned ? "Mentioned" : "Not mentioned"}
              </span>
              <span className="truncate text-xs text-muted">
                {r.competitors_mentioned.length ? `vs ${r.competitors_mentioned.join(", ")}` : "No competitors mentioned"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function ResponseEvidenceDrawer({
  evidence,
  onClose,
}: {
  evidence: SovEvidence | "loading" | null;
  onClose: () => void;
}) {
  return (
    <EvidenceDrawerShell
      open={evidence !== null}
      loading={evidence === "loading"}
      onClose={onClose}
      ariaLabel="Response evidence"
    >
      {evidence && evidence !== "loading" && (
        <div className="space-y-4 text-sm">
          <div>
            <p className="text-xs uppercase tracking-wider text-muted">Prompt</p>
            <p className="mt-1">{evidence.prompt}</p>
          </div>
          <div className="flex gap-4 text-xs text-muted">
            <span>{evidence.platform_label}</span>
            <span>Run {fmtDate(evidence.run_date)}</span>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wider text-muted">Stored response excerpt</p>
            <p className="mt-1 whitespace-pre-wrap rounded-lg bg-surface-raised p-3 text-xs leading-relaxed text-muted">
              {evidence.response_excerpt}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wider text-muted">Mentions detected</p>
            {evidence.mentions.length === 0 ? (
              <p className="mt-1 text-xs text-muted">No mentions detected in this response.</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {evidence.mentions.map((m, i) => (
                  <li key={i} className="text-xs">
                    <span className="font-medium">{m.normalized_name}</span>
                    <span className="text-muted"> ({m.entity_type}) &mdash; matched &quot;{m.raw_matched_text}&quot;</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <EvidenceField label="Execution status" value={evidence.execution_status} />
            <EvidenceField label="Owning URL" value={evidence.owning_url ?? "None set"} />
          </div>
          <div>
            <p className="text-xs uppercase tracking-wider text-muted">Cited domains</p>
            <p className="mt-1 text-xs">{evidence.cited_domains.join(", ") || "None detected"}</p>
          </div>
          {evidence.required_components.length > 0 && (
            <div>
              <p className="text-xs uppercase tracking-wider text-muted">Required components</p>
              <ul className="mt-1 space-y-1">
                {evidence.required_components.map((c, i) => (
                  <li key={i} className="text-xs">
                    <span className={c.present ? "text-emerald-a" : "text-pink-a"}>
                      {c.present ? "Present" : "Missing"}
                    </span>{" "}
                    {c.component}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </EvidenceDrawerShell>
  );
}

export function SovReport() {
  const { scope, days, compare } = useReportContext();
  const [data, setData] = useState<SovReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<View>({ type: "overview" });
  const [topicData, setTopicData] = useState<SovTopicDrilldown | null>(null);
  const [promptData, setPromptData] = useState<SovPromptDrilldown | null>(null);
  const [evidence, setEvidence] = useState<SovEvidence | "loading" | null>(null);
  const [showRanking, setShowRanking] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchSovReport(scope, days, compare)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.propertyId, days, compare, attempt]);

  useEffect(() => {
    if (view.type !== "topic" && view.type !== "prompt") return;
    if (data === null || data.scope_required || !data.has_competitors) return;
    fetchSovTopicDrilldown(data.property_id, view.topicId, days)
      .then(setTopicData)
      .catch(() => setTopicData(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.type === "topic" || view.type === "prompt" ? view.topicId : null, days]);

  useEffect(() => {
    if (view.type !== "prompt") return;
    if (data === null || data.scope_required || !data.has_competitors) return;
    fetchSovPromptDrilldown(data.property_id, view.promptId, days)
      .then(setPromptData)
      .catch(() => setPromptData(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.type === "prompt" ? view.promptId : null, days]);

  function openEvidence(responseId: number) {
    if (data === null || data.scope_required || !data.has_competitors) return;
    setEvidence("loading");
    fetchSovEvidence(data.property_id, responseId)
      .then(setEvidence)
      .catch(() => setEvidence(null));
  }

  if (error) return <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />;
  if (!data) return <p className="text-sm text-muted">Loading AI Share of Voice report...</p>;
  if (data.scope_required) return <EmptyState title="Select a property" body={data.message} />;
  if (!data.has_competitors) {
    return <EmptyState title="No competitors configured" body={data.message} />;
  }

  return (
    <div className="space-y-6">
      <p className="text-xs text-muted" title={data.tooltips.ai_share_of_voice}>
        {data.tooltips.ai_share_of_voice}
      </p>

      {view.type === "overview" && (
        <>
          <Overview report={data} onOpenRanking={() => setShowRanking(true)} />

          <Section title="Trend" sub="Periods below the minimum tested-response sample show insufficient rather than a misleading line.">
            <Trend report={data} />
          </Section>

          <Section title="Share of Voice by platform">
            <ByPlatform report={data} />
          </Section>

          <Section
            title="Share of Voice by topic"
            sub="Overall Share of Voice can hide topic-level weakness. Click a topic to drill into its prompts."
          >
            <ByTopic rows={data.by_topic} onOpenTopic={(topicId) => setView({ type: "topic", topicId })} />
          </Section>
        </>
      )}

      {view.type === "topic" && topicData && (
        <TopicDrilldown
          data={topicData}
          onBack={() => setView({ type: "overview" })}
          onOpenPrompt={(promptId) => setView({ type: "prompt", topicId: view.topicId, promptId })}
        />
      )}

      {view.type === "prompt" && promptData && (
        <PromptDrilldown
          data={promptData}
          onBack={() => setView({ type: "topic", topicId: view.topicId })}
          onOpenEvidence={openEvidence}
        />
      )}

      <ResponseEvidenceDrawer evidence={evidence} onClose={() => setEvidence(null)} />

      {showRanking && (
        <SovRankingPanel propertyId={data.property_id} days={days} onClose={() => setShowRanking(false)} />
      )}
    </div>
  );
}
