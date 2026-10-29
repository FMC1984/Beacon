"use client";

import Link from "next/link";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { ImpactPanel } from "@/components/observatory/GapsImpactPanels";
import { AlertsPanel } from "@/components/observatory/IntelligencePanels";
import { BenchmarkPanel } from "@/components/observatory/BenchmarkPanel";
import { PlatformPanel } from "@/components/observatory/StandingPanels";
import { RetestPanel } from "@/components/observatory/RetestPanel";
import { ThisWeekStrip } from "@/components/observatory/ThisWeekStrip";
import { VisibilityHero } from "@/components/observatory/VisibilityHero";
import { EvidenceDrawer, PositionPanel, SentimentPanel, useEvidenceDrawer } from "@/components/observatory/DrilldownPanels";
import { DataLabelBadge, LoadState, NeedsProperty, ObsMetricCard, Panel, ShareBar, useLoad } from "@/components/observatory/ui";
import { fetchOverview, fetchTrendsMulti, fmtRate } from "@/lib/observatory";

// AI Visibility is the hero, so it is not in the grid. Prompt Coverage is set
// coverage rather than a daily rate, so it has no series and no sparkline.
const SUPPORTING = [
  "citation_rate",
  "share_of_voice",
  "recommendation_rate",
  "ai_sentiment",
  "citation_share",
  "competitor_win_rate",
  "prompt_coverage",
] as const;

const WITH_SERIES = ["ai_visibility", ...SUPPORTING.filter((k) => k !== "prompt_coverage")];

export default function ObservatoryOverviewPage() {
  const { propertyId, days, meta, withScope } = useObservatory();
  const drawer = useEvidenceDrawer();
  const { data, error, loading, retry } = useLoad(
    propertyId === null ? null : () => fetchOverview(propertyId, days),
    [propertyId, days]
  );
  const trends = useLoad(
    propertyId === null ? null : () => fetchTrendsMulti(propertyId, WITH_SERIES, days),
    [propertyId, days]
  );
  if (propertyId === null) return <NeedsProperty />;

  const none = data !== null && data.sample.eligible_responses === 0;
  const seriesFor = (key: string) => trends.data?.metrics[key]?.series;
  return (
    <LoadState
      loading={loading && !data}
      error={error}
      retry={retry}
      empty={{
        when: none,
        title: "No AI observations in this window yet",
        body: "Generate the prompt library and run a few prompts from the Prompts tab. One shared market run scores every property in the market.",
      }}
    >
      {data && (
        <div className="space-y-6">
          <AlertsPanel propertyId={data.property_id} />
          <p className="text-xs text-muted">
            {data.sample.eligible_responses} monitored AI response{data.sample.eligible_responses === 1 ? "" : "s"} scored
            for {data.property_name}, {data.window.start} to {data.window.end}. Compared with {data.previous_window.start} to{" "}
            {data.previous_window.end}.
          </p>

          <VisibilityHero
            propertyId={data.property_id}
            days={days}
            metric={data.metrics.ai_visibility}
            series={seriesFor("ai_visibility") ?? []}
            window={data.window}
            onDrill={drawer.open}
          />

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {SUPPORTING.map((k) => (
              <ObsMetricCard
                key={k}
                metric={data.metrics[k]}
                onDrill={k === "prompt_coverage" ? undefined : drawer.open}
                series={seriesFor(k)}
                window={data.window}
              />
            ))}
          </div>

          <ThisWeekStrip propertyId={data.property_id} />

          <RetestPanel propertyId={data.property_id} />

          <BenchmarkPanel propertyId={data.property_id} days={days} />

          <PlatformPanel propertyId={data.property_id} days={days} />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel
              title="Top cited sources"
              label="MEASURED"
              subtitle={`${data.top_sources.total_citations} citations across the scored responses`}
              actions={
                <Link href={withScope("/ai-visibility/sources")} className="text-xs text-violet-a hover:underline">
                  All sources
                </Link>
              }
            >
              {data.top_sources.domains.length === 0 ? (
                <p className="text-sm text-muted">No citations in these responses.</p>
              ) : (
                <ul className="space-y-2.5">
                  {data.top_sources.domains.map((d) => (
                    <li key={`${d.domain}-${d.source_type}`}>
                      <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="truncate">{d.domain}</span>
                        <span className="shrink-0 text-xs text-muted">
                          {d.citations} · {fmtRate(d.share)}
                        </span>
                      </div>
                      <ShareBar value={d.share} tone="cyan" />
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel
              title="How AI talks about the property"
              label="MODELED"
              subtitle="Rule-based sentiment around each mention; neutral unless the wording carries sentiment."
            >
              {(() => {
                const s = data.sentiment;
                const total = s.positive + s.neutral + s.negative;
                if (total === 0) return <p className="text-sm text-muted">The property was not mentioned in this window.</p>;
                const rows: [string, number, "emerald" | "violet" | "cyan"][] = [
                  ["Positive", s.positive, "emerald"],
                  ["Neutral", s.neutral, "cyan"],
                  ["Negative", s.negative, "violet"],
                ];
                return (
                  <ul className="space-y-2.5">
                    {rows.map(([label, n, tone]) => (
                      <li key={label}>
                        <div className="flex justify-between text-sm">
                          <span>{label}</span>
                          <span className="text-xs text-muted">
                            {n} of {total} mentions
                          </span>
                        </div>
                        <ShareBar value={n / total} tone={tone} />
                      </li>
                    ))}
                  </ul>
                );
              })()}
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <PositionPanel propertyId={data.property_id} days={days} onDrill={drawer.open} />
            <SentimentPanel propertyId={data.property_id} days={days} onDrill={drawer.open} />
          </div>

          <ImpactPanel propertyId={data.property_id} days={days} />

          {meta && (
            <section className="rounded-2xl border border-line bg-surface/60 p-5">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-medium">Reading these numbers</h2>
                {meta.data_labels.map((l) => (
                  <DataLabelBadge key={l} label={l} />
                ))}
              </div>
              <ul className="space-y-1 text-xs text-muted">
                {meta.limitations.map((l) => (
                  <li key={l}>• {l}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
      {drawer.drill && propertyId !== null && (
        <EvidenceDrawer propertyId={propertyId} metric={drawer.drill.metric} days={days} clusterId={drawer.drill.clusterId} onClose={drawer.close} />
      )}
    </LoadState>
  );
}
