"use client";

import Link from "next/link";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { ContentGapsPanel } from "@/components/observatory/GapsImpactPanels";
import { LegacyAnalysis } from "@/components/observatory/legacy/AnalysisPanel";
import { NeedsProperty, Panel } from "@/components/observatory/ui";

export default function RecommendationsPage() {
  const { propertyId, days } = useObservatory();
  if (propertyId === null) return <NeedsProperty />;
  return (
    <div className="space-y-6">
      <ContentGapsPanel propertyId={propertyId} days={days} />
      <LegacyAnalysis propertyId={propertyId} only={["recommendations"]} />
      <Panel title="Where to act" subtitle="Open content gaps also appear in the Opportunity Engine as AI Observatory actions, ranked with every other module.">
        <div className="flex flex-wrap gap-2 text-sm">
          <Link href={`/opportunities?property_id=${propertyId}`} className="rounded-xl border border-line px-3.5 py-2 hover:bg-surface-raised">
            Opportunity Engine
          </Link>
          <Link href={`/content-intelligence?property_id=${propertyId}`} className="rounded-xl border border-line px-3.5 py-2 hover:bg-surface-raised">
            Content Intelligence
          </Link>
        </div>
      </Panel>
    </div>
  );
}
