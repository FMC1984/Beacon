"use client";

import Link from "next/link";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { LoadState, NeedsProperty, ObsMetricCard, Panel, useLoad } from "@/components/observatory/ui";
import { fetchOverview } from "@/lib/observatory";

export default function CompetitorsPage() {
  const { propertyId, days } = useObservatory();
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
            <ObsMetricCard metric={data.metrics.share_of_voice} />
            <ObsMetricCard metric={data.metrics.competitor_win_rate} />
            <ObsMetricCard metric={data.metrics.citation_share} />
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
        <p className="mt-4 text-xs text-muted">
          Coming next: AI-discovered competitors. Names that keep appearing in this market&apos;s AI answers will be
          listed here with their evidence so you can confirm, ignore or add them. Until then nothing is inferred.
        </p>
      </Panel>
    </div>
  );
}
