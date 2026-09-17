"use client";

import Link from "next/link";
import { useObservatory } from "@/components/observatory/ObservatoryContext";
import { ClaimsPanel } from "@/components/observatory/IntelligencePanels";
import { NeedsProperty, Panel } from "@/components/observatory/ui";

const STATUSES: [string, string][] = [
  ["Confirmed", "Matches a fact Beacon holds for the property."],
  ["Likely accurate", "Consistent with Beacon's evidence, not directly verified."],
  ["Conflict detected", "Contradicts a fact Beacon holds, with the evidence shown."],
  ["Unable to verify", "Beacon has no reliable fact to compare against. Never treated as false."],
];

export default function AccuracyPage() {
  const { propertyId } = useObservatory();
  if (propertyId === null) return <NeedsProperty />;
  return (
    <div className="space-y-6">
      <ClaimsPanel propertyId={propertyId} />
      <Panel
        title="How accuracy is judged"
        subtitle="Claims AI answers make about the property are checked against Property Context. Beacon only says a claim conflicts when it has reliable evidence."
      >
        <ul className="grid gap-2 sm:grid-cols-2">
          {STATUSES.map(([s, d]) => (
            <li key={s} className="rounded-xl border border-line bg-surface-raised p-3 text-sm">
              <span className="font-medium">{s}</span>
              <span className="block text-xs text-muted">{d}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted">
          Absence from Beacon&apos;s records is never treated as proof a claim is false. Keep{" "}
          <Link href={`/property-context?property_id=${propertyId}`} className="text-violet-a hover:underline">
            Property Context
          </Link>{" "}
          current so claims can be verified.
        </p>
      </Panel>
    </div>
  );
}
