"use client";

import Link from "next/link";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { CandidatesPanel } from "@/components/observatory/IntelligencePanels";
import { EvidenceDrawer, useEvidenceDrawer } from "@/components/observatory/DrilldownPanels";
import { TopicRankingsGrid } from "@/components/observatory/RankingPanels";
import { LoadState, NeedsProperty, ObsMetricCard, Panel, useLoad } from "@/components/observatory/ui";
import { fetchOverview } from "@/lib/observatory";

export default function CompetitorsPage() {
  const { propertyId, days } = useObservatory();
  const drawer = useEvidenceDrawer();
  const { data, error, loading, retry } = useLoad(
    propertyId === null ? null : () => fetchOverview(propertyId, days),
    [propertyId, days]
  );
  if (propertyId === null) return <NeedsProperty />;

  return (
    <div className="space-y-6">
      <LoadState loading={loading && !data} error={error} retry={retry}>
        {data && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <ObsMetricCard metric={data.metrics.share_of_voice} onDrill={drawer.open} />
            <ObsMetricCard metric={data.metrics.competitor_win_rate} onDrill={drawer.open} />
            <ObsMetricCard metric={data.metrics.citation_share} onDrill={drawer.open} />
          </div>
        )}
      </LoadState>

      <Panel
        title="Tracked competitors"
        subtitle="Competitor metrics count only competitors you track for this property. Beacon never guesses who the competition is."
      >
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/competitors?property_id=${propertyId}`}
            className="rounded-xl bg-violet-a px-3.5 py-2 text-sm font-medium text-background"
          >
            Manage tracked competitors
          </Link>
          <Link
            href={`/reports/share-of-voice?property_id=${propertyId}`}
            className="rounded-xl border border-line px-3.5 py-2 text-sm hover:bg-surface-raised"
          >
            Competitive ranking report
          </Link>
        </div>
      </Panel>

      <TopicRankingsGrid propertyId={propertyId} days={days} />
      <CandidatesPanel propertyId={propertyId} />
      {drawer.drill && (
        <EvidenceDrawer propertyId={propertyId} metric={drawer.drill.metric} days={days} onClose={drawer.close} />
      )}
    </div>
  );
}
